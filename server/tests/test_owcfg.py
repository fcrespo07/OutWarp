from __future__ import annotations

import json
from pathlib import Path

from outwarp_server.config import ServerConfig
from outwarp_server.owcfg import build_owcfg, write_owcfg


def _make_server_config() -> ServerConfig:
    return ServerConfig(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="s3cr3t",
        cert_path="/etc/outwarp/cert.pem",
        key_path="/etc/outwarp/key.pem",
        cert_fingerprint_sha256="AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89",
        wg_private_key="server_priv",
        wg_public_key="server_pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=[],
    )


def test_build_owcfg_has_all_sections() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["schema_version"] == 1
    assert "server" in cfg
    assert "tls" in cfg
    assert "tunnel" in cfg
    assert "wireguard" in cfg
    assert "routing" in cfg
    assert "reconnect" in cfg


def test_build_owcfg_server_section() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["server"]["endpoint"] == "203.0.113.42"
    assert cfg["server"]["port"] == 443
    assert cfg["server"]["http_upgrade_path_prefix"] == "s3cr3t"


def test_build_owcfg_tls_fingerprint() -> None:
    scfg = _make_server_config()
    cfg = build_owcfg(scfg, "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["tls"]["cert_fingerprint_sha256"] == scfg.cert_fingerprint_sha256


def test_build_owcfg_wireguard_section() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    wg = cfg["wireguard"]
    assert wg["client_private_key"] == "client_priv"
    assert wg["server_public_key"] == "server_pub"
    assert wg["client_address"] == "10.0.0.2/32"
    assert wg["tunnel_name"] == "OutWarp"
    assert wg["mtu"] == 1380


def test_build_owcfg_name_is_client_name() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["name"] == "laptop"


def test_build_owcfg_tunnel_points_to_loopback() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["tunnel"]["remote_host"] == "127.0.0.1"
    assert cfg["tunnel"]["remote_port"] == 51820


def test_build_owcfg_routing_bypass() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert "203.0.113.42" in cfg["routing"]["bypass_ips"]


def test_write_owcfg(tmp_path: Path) -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    out = tmp_path / "laptop.owcfg"
    write_owcfg(cfg, out)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["server"]["endpoint"] == "203.0.113.42"


def test_write_owcfg_is_0600(tmp_path: Path) -> None:
    """The .owcfg embeds a fresh WireGuard client private key — leaving it
    world-readable lets any local user impersonate that client. The atomic
    mkstemp+replace pattern guarantees 0o600 even on a default 0o022 umask."""
    import os
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    out = tmp_path / "laptop.owcfg"
    # Set an explicitly permissive umask so we'd see a 0o644 file under the
    # old write_text() path. The fix has to win regardless.
    old_umask = os.umask(0o022)
    try:
        write_owcfg(cfg, out)
    finally:
        os.umask(old_umask)
    assert out.stat().st_mode & 0o777 == 0o600


def test_write_owcfg_atomic_on_failure(tmp_path: Path) -> None:
    """If os.replace fails (e.g. cross-device), the temp file must be removed
    so we don't leak a half-written .owcfg with the WG key in /etc/outwarp/."""
    import contextlib
    from unittest.mock import patch
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    out = tmp_path / "laptop.owcfg"
    with patch("outwarp_server.config.os.replace", side_effect=OSError("EXDEV")), \
         contextlib.suppress(OSError):
        write_owcfg(cfg, out)
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == [], f"leaked temp files: {leftovers}"


def test_build_owcfg_omits_psk_and_meta_by_default() -> None:
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert "preshared_key" not in cfg["wireguard"]
    assert "meta" not in cfg


def test_build_owcfg_includes_psk_when_given() -> None:
    cfg = build_owcfg(
        _make_server_config(), "laptop", "client_priv", "10.0.0.2/32",
        preshared_key="cHNrMDAw",
    )
    assert cfg["wireguard"]["preshared_key"] == "cHNrMDAw"


def test_build_owcfg_includes_expiry_when_given() -> None:
    cfg = build_owcfg(
        _make_server_config(), "laptop", "client_priv", "10.0.0.2/32",
        expires_at="2030-01-01",
    )
    assert cfg["meta"]["expires_at"] == "2030-01-01"


def test_psk_and_expiry_roundtrip_to_client(tmp_path: Path) -> None:
    try:
        from outwarp.config import ClientConfig
    except ImportError:
        import pytest
        pytest.skip("Client package not installed in this environment")

    cfg = build_owcfg(
        _make_server_config(), "laptop", "client_priv", "10.0.0.2/32",
        preshared_key="cHNrMDAw", expires_at="2030-01-01",
    )
    out = tmp_path / "laptop.owcfg"
    write_owcfg(cfg, out)
    client_cfg = ClientConfig.load(out)
    assert client_cfg.wireguard.preshared_key == "cHNrMDAw"
    assert client_cfg.expires_at == "2030-01-01"


def test_warpcfg_compatible_with_client_schema(tmp_path: Path) -> None:
    """Verify the .owcfg can be loaded by the client's ClientConfig parser."""
    # This import works because the client package is installed in the same venv
    try:
        from outwarp.config import ClientConfig
    except ImportError:
        import pytest
        pytest.skip("Client package not installed in this environment")

    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    out = tmp_path / "laptop.owcfg"
    write_owcfg(cfg, out)
    client_cfg = ClientConfig.load(out)
    assert client_cfg.server.endpoint == "203.0.113.42"
    assert client_cfg.wireguard.client_private_key == "client_priv"
