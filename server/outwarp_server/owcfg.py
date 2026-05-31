from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from outwarp_server.config import ServerConfig, _atomic_write_secret


def build_owcfg(
    server_config: ServerConfig,
    client_name: str,
    client_private_key: str,
    client_address: str,
    preshared_key: str = "",
    expires_at: str = "",
) -> dict[str, Any]:
    """Build the .owcfg dict that the client expects.

    `preshared_key` and `expires_at` are optional and only written when set, so
    a .owcfg built without them stays byte-for-byte compatible with older
    clients (which ignore unknown keys anyway).
    """
    wireguard: dict[str, Any] = {
        "tunnel_name": "OutWarp",
        "client_address": client_address,
        "client_private_key": client_private_key,
        "server_public_key": server_config.wg_public_key,
        "dns": ["1.1.1.1"],
        "mtu": 1380,
    }
    if preshared_key:
        wireguard["preshared_key"] = preshared_key

    owcfg: dict[str, Any] = {
        "schema_version": 1,
        "name": client_name,
        "server": {
            "endpoint": server_config.endpoint,
            "port": server_config.port,
            "http_upgrade_path_prefix": server_config.http_upgrade_path_prefix,
        },
        "tls": {
            "cert_fingerprint_sha256": server_config.cert_fingerprint_sha256,
        },
        "tunnel": {
            "local_port": server_config.wg_listen_port,
            "remote_host": "127.0.0.1",
            "remote_port": server_config.wg_listen_port,
        },
        "wireguard": wireguard,
        "routing": {
            "bypass_ips": [server_config.endpoint],
        },
        "reconnect": {
            "max_attempts": 5,
            "delays_seconds": [5, 10, 20, 30, 60],
        },
    }
    if expires_at:
        owcfg["meta"] = {"expires_at": expires_at}
    return owcfg


def write_owcfg(warpcfg: dict[str, Any], path: Path) -> None:
    """Write a .owcfg file with 0o600 permissions.

    The owcfg embeds the client's freshly-generated WireGuard private key, so
    a default-umask 0o644 (the prior behaviour of ``Path.write_text``) leaves
    the key world-readable on multi-user boxes — a local user can rip it and
    impersonate that client. Atomic rename ensures the file never exists in
    a half-written state with relaxed perms either.
    """
    payload = json.dumps(warpcfg, indent=2, ensure_ascii=False)
    _atomic_write_secret(path, payload)
