"""Pure operations: add/revoke/rotate/restart shared by the CLI, TUI and ServerManager.

These functions own the state-changing logic (keygen, IP allocation, WG hot-add,
config persistence, .owcfg generation) and return structured results. The TUI
consumes them to render preview/result cards; the CLI wraps them with rich
formatting.
"""

from __future__ import annotations

import hashlib
import logging
import time
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
    # Set when the profile was issued for enrolment: the client generates its own
    # keypair and redeems this before it can connect. Empty for legacy profiles
    # that carry a server-generated private key.
    enrollment_expires_at: int = 0


@dataclass
class CompleteEnrollmentResult:
    client: ClientEntry
    config: ServerConfig
    hot_added: bool
    wg_persist_warning: str | None


@dataclass
class RevokeResult:
    name: str
    config: ServerConfig
    hot_removed: bool
    wg_persist_warning: str | None


@dataclass
class RotateClientResult:
    client: ClientEntry
    config: ServerConfig
    owcfg_path: Path
    owcfg_sha256: str
    hot_rotated: bool
    wg_persist_warning: str | None


@dataclass
class RestartResult:
    wg_conf_written: bool
    wg_restarted: bool
    wstunnel_restarted: bool
    errors: list[str]


def _format_fingerprint(digest: str) -> str:
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2)).upper()


def _ensure_spki(config: ServerConfig) -> ServerConfig:
    """Backfill the TLS public-key pin for servers set up before it existed.

    Read from the certificate already on disk, so it is exactly what the client
    will see on the wire. Without it those servers keep issuing profiles pinned
    to the certificate, which `renew-cert` would then invalidate. Best-effort:
    an unreadable certificate is not a reason to refuse to issue a profile.
    """
    if config.spki_sha256:
        return config
    from outwarp_server.crypto import compute_spki_fingerprint
    try:
        spki = compute_spki_fingerprint(Path(config.cert_path))
    except Exception as exc:
        log.warning("Could not derive the TLS key pin from %s: %s", config.cert_path, exc)
        return config
    return replace(config, spki_sha256=spki)


def add_client(
    config: ServerConfig,
    name: str,
    *,
    config_path: Path,
    output_dir: Path | None = None,
    expires_at: str = "",
    enroll: bool = False,
    enroll_ttl_seconds: int = 0,
) -> AddClientResult:
    """Register a new client, persist server config, and write its .owcfg.

    With ``enroll`` the server does not generate a keypair at all: it reserves
    the name, IP and preshared key, mints a one-time token, and leaves the peer
    unregistered until the client posts its own public key. That is the mode
    where a client private key never exists on this machine — see
    :mod:`outwarp_server.enrollment`. Without it, the legacy behaviour applies
    and the private key is generated here and embedded in the profile.

    Raises ValueError if the name is invalid, already exists, or the IP pool is
    exhausted. The name is validated here because operations.py is the shared
    entry-point for the CLI, TUI and ServerManager — centralising the check
    prevents path traversal via a crafted name (e.g. '../evil') when the name
    is used to build the .owcfg filename.
    """
    # Late import avoids a module-level circular dependency (server_manager
    # imports from operations via CLI/TUI, not directly, but being careful).
    from outwarp_server.server_manager import validate_client_name
    name = validate_client_name(name)

    for c in config.clients:
        if c.name == name:
            raise ValueError(f"Client '{name}' already exists.")

    config = _ensure_spki(config)

    client_private_key = ""
    client_public_key = ""
    if not enroll:
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

    # Nothing to add to the interface yet in enrolment mode — there is no public
    # key until the client redeems its token.
    hot_added = not enroll
    if not enroll:
        try:
            add_peer_live(client_public_key, client_address, psk=psk)
        except Exception as exc:
            log.warning("Could not hot-add peer (WireGuard may not be running): %s", exc)
            hot_added = False

    enrollment_token = ""
    enrollment_expires_at = 0
    if enroll:
        from outwarp_server import enrollment
        ttl = enroll_ttl_seconds or enrollment.DEFAULT_TTL_SECONDS
        enrollment_token = enrollment.issue(
            config_path.parent, name, ttl_seconds=ttl
        )
        enrollment_expires_at = int(time.time()) + ttl

    new_client = ClientEntry(
        name=name,
        public_key=client_public_key,
        address=client_address,
        psk=psk,
        expires_at=expires_at,
    )
    updated = replace(config, clients=[*config.clients, new_client])
    updated.save(config_path)

    wg_persist_warning = _persist_wg_config(updated)

    owcfg = build_owcfg(
        config,
        name,
        client_private_key,
        client_address,
        preshared_key=psk,
        expires_at=expires_at,
        enrollment_token=enrollment_token,
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
        enrollment_expires_at=enrollment_expires_at,
    )


def complete_enrollment(
    config: ServerConfig,
    name: str,
    client_public_key: str,
    *,
    config_path: Path,
) -> CompleteEnrollmentResult:
    """Attach `client_public_key` to the slot reserved for `name` and admit it.

    Called from the enrolment listener once a token has been redeemed. The token
    store already marked the token spent, so this runs at most once per token
    even if the client retries.

    Raises KeyError if the slot is gone (the admin revoked the client between
    issuing and redeeming) and ValueError if the slot already has a key.
    """
    target = next((c for c in config.clients if c.name == name), None)
    if target is None:
        raise KeyError(
            f"Client '{name}' is no longer registered — the reservation was revoked."
        )
    if target.public_key:
        raise ValueError(f"Client '{name}' already has a registered public key.")

    hot_added = True
    try:
        add_peer_live(client_public_key, target.address, psk=target.psk)
    except Exception as exc:
        log.warning("Could not hot-add enrolled peer (WireGuard may not be running): %s", exc)
        hot_added = False

    enrolled = replace(target, public_key=client_public_key)
    updated = replace(
        config,
        clients=[enrolled if c.name == name else c for c in config.clients],
    )
    updated.save(config_path)

    return CompleteEnrollmentResult(
        client=enrolled,
        config=updated,
        hot_added=hot_added,
        wg_persist_warning=_persist_wg_config(updated),
    )


def _persist_wg_config(config: ServerConfig) -> str | None:
    """Write the OS-level WG config, returning a warning string on failure."""
    # Late import so test patches on `outwarp_server.platforms.get_server_platform`
    # take effect (module-level imports would freeze the reference at import time).
    from outwarp_server.platforms import PlatformError, get_server_platform
    try:
        get_server_platform().install_wg_config(build_server_wg_conf(config))
    except PlatformError as exc:
        log.warning("Could not persist WG config to OS location: %s", exc)
        return str(exc)
    return None


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

    # Revoking must also kill any token still outstanding for this name,
    # otherwise the slot comes back the moment someone redeems it.
    from outwarp_server import enrollment
    enrollment.revoke(config_path.parent, name)

    # A client that never enrolled has no peer on the interface to remove.
    hot_removed = True
    if target.public_key:
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


def rotate_client(
    config: ServerConfig,
    name: str,
    *,
    config_path: Path,
    output_dir: Path | None = None,
) -> RotateClientResult:
    """Generate a fresh WG keypair + PSK for an existing client.

    The old public key is removed from the peer list; the new one is added.
    The client's IP address and expiry are preserved. Returns a new .owcfg that
    must be re-distributed to the client — the previous one becomes invalid
    as soon as this call returns.

    Raises ValueError if the client is not found.
    """
    from outwarp_server.server_manager import validate_client_name
    name = validate_client_name(name)

    target = next((c for c in config.clients if c.name == name), None)
    if target is None:
        raise ValueError(f"Client '{name}' not found.")

    config = _ensure_spki(config)
    new_private, new_public = generate_wg_keypair()
    try:
        new_psk = generate_psk()
    except Exception as exc:
        log.warning("Could not generate preshared key on rotate (continuing without one): %s", exc)
        new_psk = ""

    hot_rotated = True
    try:
        remove_peer_live(target.public_key)
    except Exception as exc:
        log.warning("Could not hot-remove old peer (WireGuard may not be running): %s", exc)
        hot_rotated = False
    try:
        add_peer_live(new_public, target.address, psk=new_psk)
    except Exception as exc:
        log.warning("Could not hot-add rotated peer (WireGuard may not be running): %s", exc)
        hot_rotated = False

    updated_clients = [
        ClientEntry(
            name=c.name, public_key=new_public, address=c.address,
            psk=new_psk, expires_at=c.expires_at,
        ) if c.name == name else c
        for c in config.clients
    ]
    updated = replace(config, clients=updated_clients)
    updated.save(config_path)

    wg_persist_warning: str | None = None
    from outwarp_server.platforms import PlatformError, get_server_platform
    try:
        get_server_platform().install_wg_config(build_server_wg_conf(updated))
    except PlatformError as exc:
        log.warning("Could not persist WG config to OS location: %s", exc)
        wg_persist_warning = str(exc)

    new_client = next(c for c in updated.clients if c.name == name)
    owcfg = build_owcfg(
        config,
        name,
        new_private,
        target.address,
        preshared_key=new_psk,
        expires_at=target.expires_at,
    )
    owcfg_dir = output_dir or Path.cwd()
    owcfg_path = owcfg_dir / f"{name}.owcfg"
    write_owcfg(owcfg, owcfg_path)

    digest = hashlib.sha256(owcfg_path.read_bytes()).hexdigest()

    return RotateClientResult(
        client=new_client,
        config=updated,
        owcfg_path=owcfg_path,
        owcfg_sha256=_format_fingerprint(digest),
        hot_rotated=hot_rotated,
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
