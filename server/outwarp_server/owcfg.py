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
    enrollment_token: str = "",
) -> dict[str, Any]:
    """Build the .owcfg dict that the client expects.

    `preshared_key` and `expires_at` are optional and only written when set, so
    a .owcfg built without them stays byte-for-byte compatible with older
    clients (which ignore unknown keys anyway).

    With `enrollment_token` the profile is a v3 one: it carries no
    `client_private_key` at all, and the client generates its own keypair on
    import and redeems the token to register the public half. That is the shape
    that keeps client private keys off the server and out of the delivery
    channel — see :mod:`outwarp_server.enrollment`.
    """
    wireguard: dict[str, Any] = {
        "tunnel_name": "OutWarp",
        "client_address": client_address,
        "server_public_key": server_config.wg_public_key,
        "dns": ["1.1.1.1"],
        "mtu": 1380,
    }
    if not enrollment_token:
        wireguard["client_private_key"] = client_private_key
    if preshared_key:
        wireguard["preshared_key"] = preshared_key

    # Behind Caddy the public certificate is a real one that renews every ~60
    # days, so there is nothing stable to pin: the client validates the chain
    # instead. Pinning here would break every profile at the first renewal.
    #
    # In the self-signed branch, spki_sha256 is what makes `renew-cert`
    # non-breaking, so it is emitted whenever the server has one — but its
    # presence alone bumps the profile to v2, because a v1 client would silently
    # ignore the field and keep pinning the certificate. Servers set up before
    # the field existed keep issuing v1.
    tls: dict[str, Any]
    if server_config.behind_reverse_proxy:
        tls = {"verify": "ca"}
        schema_version = 2
    else:
        tls = {"cert_fingerprint_sha256": server_config.cert_fingerprint_sha256}
        schema_version = 1
        if server_config.spki_sha256:
            tls["spki_sha256"] = server_config.spki_sha256
            schema_version = 2

    owcfg: dict[str, Any] = {
        "schema_version": schema_version,
        "name": client_name,
        "server": {
            "endpoint": server_config.endpoint,
            "port": server_config.port,
            "http_upgrade_path_prefix": server_config.http_upgrade_path_prefix,
        },
        "tls": tls,
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
    if enrollment_token:
        owcfg["schema_version"] = 3
        owcfg["enrollment"] = {
            "token": enrollment_token,
            "url": server_config.enroll_url,
        }
    if expires_at:
        owcfg["meta"] = {"expires_at": expires_at}
    return owcfg


def write_owcfg(warpcfg: dict[str, Any], path: Path) -> None:
    """Write a .owcfg file with 0o600 permissions.

    A v1/v2 owcfg embeds the client's WireGuard private key, so a default-umask
    0o644 (the prior behaviour of ``Path.write_text``) leaves the key
    world-readable on multi-user boxes — a local user can rip it and impersonate
    that client. Atomic rename ensures the file never exists in a half-written
    state with relaxed perms either.

    A v3 (enrolment) owcfg has no private key, but it does carry a live one-time
    token and the preshared key, so the same handling applies.
    """
    payload = json.dumps(warpcfg, indent=2, ensure_ascii=False)
    _atomic_write_secret(path, payload)
