from __future__ import annotations

import logging
import os
import secrets
import shutil
from pathlib import Path

from outwarp_server.config import ServerConfig
from outwarp_server.crypto import generate_tls_cert, generate_wg_keypair

log = logging.getLogger(__name__)


def run_init(config_dir: Path) -> int:
    """Non-interactive server initialization driven by environment variables.

    Reads:
      OUTWARP_ENDPOINT        (required) — public IP or domain clients will connect to
      OUTWARP_PORT            (default 443) — wstunnel WSS listen port
      OUTWARP_WG_PORT         (default 51820) — WireGuard loopback listen port
      OUTWARP_SUBNET          (default 10.0.0.0/24) — WireGuard subnet
      OUTWARP_SERVER_ADDRESS  (default <subnet>.1/24) — server WG address
      OUTWARP_UPGRADE_PATH    (optional) — HTTP upgrade path prefix; auto-generated if absent

    Idempotent: if server_config.json already exists the function returns 0
    immediately without touching keys, certificates, or config.

    WireGuard is NOT brought up here — that happens when `serve` starts
    ServerManager, which calls platform.install_wg_config().
    """
    config_path = config_dir / "server_config.json"

    if config_path.exists():
        log.info("Config already exists at %s — skipping init", config_path)
        return 0

    endpoint = os.environ.get("OUTWARP_ENDPOINT", "").strip()
    if not endpoint:
        log.error(
            "OUTWARP_ENDPOINT is required.\n"
            "  Example: OUTWARP_ENDPOINT=203.0.113.42 outwarp-server init"
        )
        return 1

    try:
        port = int(os.environ.get("OUTWARP_PORT", "443"))
        wg_listen_port = int(os.environ.get("OUTWARP_WG_PORT", "51820"))
    except ValueError as exc:
        log.error("Invalid port value: %s", exc)
        return 1

    subnet = os.environ.get("OUTWARP_SUBNET", "10.0.0.0/24")
    default_server_addr = subnet.rsplit(".", 1)[0] + ".1/24"
    server_address = os.environ.get("OUTWARP_SERVER_ADDRESS", default_server_addr)
    upgrade_path = os.environ.get("OUTWARP_UPGRADE_PATH") or secrets.token_urlsafe(32)

    log.info("Generating TLS certificate for %s...", endpoint)
    cert_dir = config_dir / "tls"
    try:
        cert_path, key_path, fingerprint, spki = generate_tls_cert(endpoint, cert_dir)
    except Exception as exc:
        log.error("TLS cert generation failed: %s", exc)
        return 1

    log.info("Generating WireGuard server keypair...")
    wg_bin = shutil.which("wg")
    try:
        wg_priv, wg_pub = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
    except Exception as exc:
        log.error("WireGuard keygen failed: %s", exc)
        return 1

    config = ServerConfig(
        schema_version=1,
        endpoint=endpoint,
        port=port,
        http_upgrade_path_prefix=upgrade_path,
        cert_path=str(cert_path),
        key_path=str(key_path),
        cert_fingerprint_sha256=fingerprint,
        spki_sha256=spki,
        wg_private_key=wg_priv,
        wg_public_key=wg_pub,
        subnet=subnet,
        server_address=server_address,
        wg_listen_port=wg_listen_port,
        clients=[],
    )

    try:
        config.save(config_path)
    except OSError as exc:
        log.error("Failed to save config to %s: %s", config_path, exc)
        return 1

    log.info("Config saved to %s", config_path)
    log.info("  Endpoint:    %s:%s", endpoint, port)
    log.info("  WG subnet:   %s  server=%s", subnet, server_address)
    log.info("  Fingerprint: %s", fingerprint)
    log.info("Init complete — start the server with: outwarp-server serve")
    return 0
