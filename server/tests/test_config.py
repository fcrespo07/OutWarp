from __future__ import annotations

import json
from pathlib import Path

import pytest

from outwarp_server.config import (
    ClientEntry,
    ConfigError,
    ServerConfig,
    default_config_path,
)

VALID: dict = {
    "schema_version": 1,
    "endpoint": "203.0.113.42",
    "port": 443,
    "http_upgrade_path_prefix": "s3cr3t-path",
    "cert_path": "/etc/outwarp/cert.pem",
    "key_path": "/etc/outwarp/key.pem",
    "cert_fingerprint_sha256": (
        "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:"
        "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89"
    ),
    "wg_private_key": "cHJpdmF0ZWtleQ==",
    "wg_public_key": "cHVibGlja2V5",
    "subnet": "10.0.0.0/24",
    "server_address": "10.0.0.1/24",
    "wg_listen_port": 51820,
    "clients": [
        {"name": "laptop", "public_key": "bGFwdG9wa2V5", "address": "10.0.0.2/32"},
    ],
}


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "server_config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_valid(tmp_path: Path) -> None:
    cfg = ServerConfig.load(_write(tmp_path, VALID))
    assert cfg.endpoint == "203.0.113.42"
    assert cfg.port == 443
    assert cfg.wg_listen_port == 51820
    assert cfg.subnet == "10.0.0.0/24"
    assert len(cfg.clients) == 1
    assert cfg.clients[0].name == "laptop"
    assert cfg.clients[0].address == "10.0.0.2/32"


def test_save_roundtrip(tmp_path: Path) -> None:
    src = _write(tmp_path, VALID)
    cfg = ServerConfig.load(src)
    dest = tmp_path / "out.json"
    cfg.save(dest)
    cfg2 = ServerConfig.load(dest)
    assert cfg == cfg2


def test_save_is_0600(tmp_path: Path) -> None:
    """server_config.json embeds the WG private key (and the wstunnel
    path-prefix). 0o644 is a local-user information leak — must be 0o600
    regardless of the system umask."""
    import os
    src = _write(tmp_path, VALID)
    cfg = ServerConfig.load(src)
    dest = tmp_path / "out.json"
    old_umask = os.umask(0o022)
    try:
        cfg.save(dest)
    finally:
        os.umask(old_umask)
    assert dest.stat().st_mode & 0o777 == 0o600


def test_empty_clients_list(tmp_path: Path) -> None:
    data = {**VALID, "clients": []}
    cfg = ServerConfig.load(_write(tmp_path, data))
    assert cfg.clients == []


def test_missing_clients_defaults_empty(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "clients"}
    cfg = ServerConfig.load(_write(tmp_path, data))
    assert cfg.clients == []


def test_missing_required_field(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "endpoint"}
    with pytest.raises(ConfigError, match="endpoint"):
        ServerConfig.load(_write(tmp_path, data))


def test_invalid_port(tmp_path: Path) -> None:
    data = {**VALID, "port": 99999}
    with pytest.raises(ConfigError, match="port"):
        ServerConfig.load(_write(tmp_path, data))


def test_invalid_wg_port(tmp_path: Path) -> None:
    data = {**VALID, "wg_listen_port": -1}
    with pytest.raises(ConfigError, match="wg_listen_port"):
        ServerConfig.load(_write(tmp_path, data))


def test_unsupported_schema_version(tmp_path: Path) -> None:
    data = {**VALID, "schema_version": 99}
    with pytest.raises(ConfigError, match="schema_version"):
        ServerConfig.load(_write(tmp_path, data))


def test_file_not_found() -> None:
    with pytest.raises(ConfigError, match="not found"):
        ServerConfig.load(Path("/nonexistent/config.json"))


def test_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ not json }", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        ServerConfig.load(p)


def test_default_config_path_is_absolute() -> None:
    assert default_config_path().is_absolute()


def test_client_entry_frozen() -> None:
    c = ClientEntry(name="test", public_key="key", address="10.0.0.2/32")
    with pytest.raises(AttributeError):
        c.name = "other"  # type: ignore[misc]


def test_client_psk_and_expiry_roundtrip(tmp_path: Path) -> None:
    data = {
        **VALID,
        "clients": [
            {
                "name": "laptop", "public_key": "k", "address": "10.0.0.2/32",
                "psk": "cHNrMDAw", "expires_at": "2030-01-01",
            },
            {"name": "old", "public_key": "k2", "address": "10.0.0.3/32"},
        ],
    }
    cfg = ServerConfig.load(_write(tmp_path, data))
    assert cfg.clients[0].psk == "cHNrMDAw"
    assert cfg.clients[0].expires_at == "2030-01-01"
    # A client without psk/expiry parses with empty defaults.
    assert cfg.clients[1].psk == ""
    assert cfg.clients[1].expires_at == ""

    dest = tmp_path / "out.json"
    cfg.save(dest)
    reloaded = ServerConfig.load(dest)
    assert reloaded == cfg
    # Empty psk/expiry are omitted from the serialized form to stay compatible.
    raw = json.loads(dest.read_text(encoding="utf-8"))
    assert "psk" not in raw["clients"][1]
    assert "expires_at" not in raw["clients"][1]
