import json
import pytest
from pathlib import Path
from outwarp.config import (
    ClientConfig,
    ConfigError,
    apply_profile_patch,
    default_config_path,
    import_owcfg,
    original_config_path,
)

VALID = {
    "schema_version": 1,
    "server": {
        "endpoint": "203.0.113.42",
        "port": 443,
        "http_upgrade_path_prefix": "s3cr3t",
    },
    "tls": {
        "cert_fingerprint_sha256": "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89",
    },
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "OutWarp",
        "client_address": "10.0.0.42/32",
        "client_private_key": "dGVzdGtleQ==",
        "server_public_key": "c2VydmVya2V5",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
    "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
}


def write_cfg(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "test.owcfg"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_valid(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.server.endpoint == "203.0.113.42"
    assert cfg.server.port == 443
    assert cfg.tunnel.local_port == 51820
    assert cfg.wireguard.tunnel_name == "OutWarp"
    assert cfg.routing.bypass_ips == ["203.0.113.42"]
    assert cfg.reconnect.max_attempts == 5


def test_reconnect_defaults_when_missing(tmp_path):
    data = {k: v for k, v in VALID.items() if k != "reconnect"}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.reconnect.max_attempts == 5
    assert cfg.reconnect.delays_seconds == [5, 10, 20, 30, 60]


def test_missing_required_field(tmp_path):
    data = {**VALID, "server": {"port": 443, "http_upgrade_path_prefix": "x"}}
    with pytest.raises(ConfigError, match="endpoint"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_invalid_port(tmp_path):
    data = {**VALID, "server": {**VALID["server"], "port": 99999}}
    with pytest.raises(ConfigError, match="port"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_bad_fingerprint(tmp_path):
    data = {**VALID, "tls": {"cert_fingerprint_sha256": "notafingerprint"}}
    with pytest.raises(ConfigError, match="cert_fingerprint_sha256"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_unsupported_schema_version(tmp_path):
    data = {**VALID, "schema_version": 99}
    with pytest.raises(ConfigError, match="schema_version"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_file_not_found():
    with pytest.raises(ConfigError, match="not found"):
        ClientConfig.load(Path("/nonexistent/path.owcfg"))


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.owcfg"
    p.write_text("{ not json }", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        ClientConfig.load(p)


def test_save_roundtrip(tmp_path):
    src = write_cfg(tmp_path, VALID)
    cfg = ClientConfig.load(src)
    dest = tmp_path / "out.json"
    cfg.save(dest)
    cfg2 = ClientConfig.load(dest)
    assert cfg == cfg2


def test_import_owcfg(tmp_path):
    src = write_cfg(tmp_path, VALID)
    dest = tmp_path / "config.json"
    cfg = import_owcfg(src, dest)
    assert dest.exists()
    assert cfg.server.port == 443


def test_import_owcfg_writes_pristine_original(tmp_path):
    src = write_cfg(tmp_path, VALID)
    dest = tmp_path / "config.json"
    import_owcfg(src, dest)
    orig = original_config_path(dest)
    assert orig.exists()
    assert ClientConfig.load(orig) == ClientConfig.load(dest)


def test_default_config_path_is_absolute():
    assert default_config_path().is_absolute()


# --- schema additions: name + mtu ---

def test_name_defaults_empty_and_roundtrips(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.name == ""
    named = {**VALID, "name": "Portátil"}
    assert ClientConfig.load(write_cfg(tmp_path, named)).name == "Portátil"


def test_mtu_defaults_and_validates(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.wireguard.mtu == 1380
    data = {**VALID, "wireguard": {**VALID["wireguard"], "mtu": 9000}}
    with pytest.raises(ConfigError, match="mtu"):
        ClientConfig.load(write_cfg(tmp_path, data))


# --- apply_profile_patch ---

def _cfg(tmp_path):
    return ClientConfig.load(write_cfg(tmp_path, VALID))


def test_apply_profile_patch_updates_fields(tmp_path):
    cfg = _cfg(tmp_path)
    out = apply_profile_patch(cfg, {
        "name": "Trabajo",
        "mtu": 1400,
        "dns": "9.9.9.9, 8.8.8.8",
        "client_address": "10.0.0.7/32",
        "bypass_ips": "203.0.113.42, 198.51.100.0/24",
        "reconnect_max_attempts": 3,
        "reconnect_delays": "2, 4, 8",
    })
    assert out.name == "Trabajo"
    assert out.wireguard.mtu == 1400
    assert out.wireguard.dns == ["9.9.9.9", "8.8.8.8"]
    assert out.wireguard.client_address == "10.0.0.7/32"
    assert out.routing.bypass_ips == ["203.0.113.42", "198.51.100.0/24"]
    assert out.reconnect.max_attempts == 3
    assert out.reconnect.delays_seconds == [2, 4, 8]
    # untouched fields preserved
    assert out.server == cfg.server
    assert out.wireguard.client_private_key == cfg.wireguard.client_private_key


def test_apply_profile_patch_empty_patch_is_noop(tmp_path):
    cfg = _cfg(tmp_path)
    assert apply_profile_patch(cfg, {}) == cfg


@pytest.mark.parametrize("patch,match", [
    ({"name": "   "}, "vacío"),
    ({"mtu": 99999}, "MTU"),
    ({"mtu": "abc"}, "MTU"),
    ({"dns": "not-an-ip"}, "DNS"),
    ({"client_address": "999.0.0.1/32"}, "IP del cliente"),
    ({"bypass_ips": "nope"}, "bypass"),
    ({"reconnect_max_attempts": 0}, "reconexión"),
    ({"reconnect_delays": ""}, "reconexión"),
    ({"reconnect_delays": "5, -1"}, "positivos"),
])
def test_apply_profile_patch_rejects_bad_input(tmp_path, patch, match):
    with pytest.raises(ConfigError, match=match):
        apply_profile_patch(_cfg(tmp_path), patch)
