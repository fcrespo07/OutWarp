"""Pure operations: add/revoke/restart shared by the CLI, TUI and ServerManager.

These functions own the state-changing logic (keygen, IP allocation, WG hot-add,
config persistence, .owcfg generation) and return structured results. The TUI
consumes them to render preview/result cards; the CLI wraps them with rich
formatting.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.crypto import generate_psk, generate_wg_keypair
from outwarp_server.ip_pool import PoolExhaustedError, next_available_ip
from outwarp_server.owcfg import build_owcfg, write_owcfg
from outwarp_server.wireguard import (
    add_peer_live,
    build_server_wg_conf,
    remove_peer_live,
)

log = logging.getLogger(__name__)


@dataclass
class AddClientResult:
    client: ClientEntry
    config: ServerConfig
    owcfg_path: Path
    owcfg_sha256: str
    hot_added: bool
    wg_persist_warning: str | None


@dataclass
class RevokeResult:
    name: str
    config: ServerConfig
    hot_removed: bool
    wg_persist_warning: str | None


@dataclass
class RestartResult:
    wg_conf_written: bool
    wg_restarted: bool
    wstunnel_restarted: bool
    errors: list[str]


def _format_fingerprint(digest: str) -> str:
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2)).upper()


def add_client(
    config: ServerConfig,
    name: str,
    *,
    config_path: Path,
    output_dir: Path | None = None,
    expires_at: str = "",
) -> AddClientResult:
    """Generate a new client, persist server config, hot-add peer, write .owcfg.

    Raises ValueError if the name already exists or the IP pool is exhausted.
    """
    for c in config.clients:
        if c.name == name:
            raise ValueError(f"Client '{name}' already exists.")

    client_private_key, client_public_key = generate_wg_keypair()
    try:
        psk = generate_psk()
    except Exception as exc:
        log.warning("Could not generate preshared key (continuing without one): %s", exc)
        psk = ""

    allocated = [c.address for c in config.clients]
    try:
        client_address = next_available_ip(
            config.subnet, config.server_address, allocated
        )
    except PoolExhaustedError as exc:
        raise ValueError(str(exc)) from exc

    hot_added = True
    try:
        add_peer_live(client_public_key, client_address, psk=psk)
    except Exception as exc:
        log.warning("Could not hot-add peer (WireGuard may not be running): %s", exc)
        hot_added = False

    new_client = ClientEntry(
        name=name,
        public_key=client_public_key,
        address=client_address,
        psk=psk,
        expires_at=expires_at,
    )
    updated = replace(config, clients=[*config.clients, new_client])
    updated.save(config_path)

    wg_persist_warning: str | None = None
    # Late import so test patches on `outwarp_server.platforms.get_server_platform`
    # take effect (module-level imports would freeze the reference at import time).
    from outwarp_server.platforms import PlatformError, get_server_platform
    try:
        get_server_platform().install_wg_config(build_server_wg_conf(updated))
    except PlatformError as exc:
        log.warning("Could not persist WG config to OS location: %s", exc)
        wg_persist_warning = str(exc)

    owcfg = build_owcfg(
        config,
        name,
        client_private_key,
        client_address,
        preshared_key=psk,
        expires_at=expires_at,
    )
    owcfg_dir = output_dir or Path.cwd()
    owcfg_path = owcfg_dir / f"{name}.owcfg"
    write_owcfg(owcfg, owcfg_path)

    digest = hashlib.sha256(owcfg_path.read_bytes()).hexdigest()

    return AddClientResult(
        client=new_client,
        config=updated,
        owcfg_path=owcfg_path,
        owcfg_sha256=_format_fingerprint(digest),
        hot_added=hot_added,
        wg_persist_warning=wg_persist_warning,
    )


def revoke_client(
    config: ServerConfig,
    name: str,
    *,
    config_path: Path,
) -> RevokeResult:
    """Remove a client from the running interface and persist the new config.

    Raises KeyError if the name is unknown.
    """
    target = next((c for c in config.clients if c.name == name), None)
    if target is None:
        raise KeyError(f"Client '{name}' not found.")

    hot_removed = True
    try:
        remove_peer_live(target.public_key)
    except Exception as exc:
        log.warning("Could not hot-remove peer (WireGuard may not be running): %s", exc)
        hot_removed = False

    updated = replace(config, clients=[c for c in config.clients if c.name != name])
    updated.save(config_path)

    wg_persist_warning: str | None = None
    from outwarp_server.platforms import PlatformError, get_server_platform
    try:
        get_server_platform().install_wg_config(build_server_wg_conf(updated))
    except PlatformError as exc:
        log.warning("Could not persist WG config to OS location: %s", exc)
        wg_persist_warning = str(exc)

    return RevokeResult(
        name=name,
        config=updated,
        hot_removed=hot_removed,
        wg_persist_warning=wg_persist_warning,
    )


def restart_services(config: ServerConfig) -> RestartResult:
    """Regenerate wg0.conf, fully restart wg-quick, then restart wstunnel.

    Order matters: if wg config write or wg restart fail, wstunnel is left
    alone — an interrupted restart that takes wstunnel down without WG is worse
    than no restart at all.
    """
    from outwarp_server.platforms import PlatformError, get_server_platform

    platform = get_server_platform()
    errors: list[str] = []
    wg_conf_written = False
    wg_restarted = False
    wstunnel_restarted = False

    try:
        platform.install_wg_config(build_server_wg_conf(config))
        wg_conf_written = True
    except PlatformError as exc:
        errors.append(f"WireGuard config: {exc}")
        return RestartResult(wg_conf_written, wg_restarted, wstunnel_restarted, errors)

    try:
        platform.restart_wg()
        wg_restarted = True
    except PlatformError as exc:
        errors.append(f"WireGuard restart: {exc}")
        return RestartResult(wg_conf_written, wg_restarted, wstunnel_restarted, errors)

    try:
        platform.restart_wstunnel_service()
        wstunnel_restarted = True
    except PlatformError as exc:
        errors.append(f"wstunnel restart: {exc}")

    return RestartResult(wg_conf_written, wg_restarted, wstunnel_restarted, errors)
