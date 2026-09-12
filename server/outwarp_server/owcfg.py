from __future__ import annotations

import base64
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

    With `enrollment_token` the profile is a v4 one: it carries no
    `client_private_key` at all, and the client generates its own keypair on
    import and redeems the token to register the public half. That is the shape
    that keeps client private keys off the server and out of the delivery
    channel — see :mod:`outwarp_server.enrollment`.

    When `server_config` has a signing key (CONCEPTO-C prop.2), the whole dict
    is embedded with a ``"signing"`` block before it's returned — see
    ``_sign_owcfg``. This only protects the profile against tampering *between*
    the server signing it and the client importing it (an email attachment
    edited in place, a USB stick, a shared drive) by someone who has the file
    but not the server's private signing key. It does **not** protect the
    first delivery from a full man-in-the-middle who can substitute both the
    profile and a freshly-generated key of their own — that gap is TOFU by
    construction and closes only on the client's *next* import from the same
    server (outwarp.profile_trust pins the key it saw first).
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
        # v4: the token is redeemed *through the transport* — the client opens
        # a wstunnel TCP forward to 127.0.0.1:remote_port on the server (see
        # enroll_server.py) over the tunnel port it already has in `server`,
        # so there is nothing else to dial. v3 carried a public HTTPS `url` on
        # a second port instead; a v3 client refuses this file with "update
        # OutWarp", which is the honest answer — it cannot enrol here.
        owcfg["schema_version"] = 4
        owcfg["enrollment"] = {
            "token": enrollment_token,
            "remote_port": server_config.enroll_port,
        }
    if expires_at:
        owcfg["meta"] = {"expires_at": expires_at}
    if server_config.owcfg_signing_private_key:
        owcfg["signing"] = _sign_owcfg(server_config, owcfg)
    return owcfg


def _canonical_json(payload: dict[str, Any]) -> bytes:
    """Deterministic serialization the client reproduces byte-for-byte to
    verify the signature — sorted keys, no incidental whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_owcfg(server_config: ServerConfig, owcfg: dict[str, Any]) -> dict[str, str]:
    from outwarp_server import minisign

    payload = _canonical_json(owcfg)  # "signing" isn't in owcfg yet at this point
    key_id = bytes.fromhex(server_config.owcfg_signing_key_id)
    private_key = base64.b64decode(server_config.owcfg_signing_private_key)
    signature = minisign.sign(
        payload, key_id, private_key,
        trusted_comment=f"OutWarp profile for {owcfg.get('name') or 'client'}",
    )
    return {"public_key": server_config.owcfg_signing_public_key, "signature": signature}


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
