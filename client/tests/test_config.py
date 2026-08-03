import json
from pathlib import Path

import pytest

from outwarp.config import (
    ClientConfig,
    ConfigError,
    apply_profile_patch,
    default_config_path,
    import_owcfg,
    import_owcfg_text,
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
        "cert_fingerprint_sha256": (
            "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:"
            "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89"
        ),
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


def test_fallback_ports_default_empty(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.server.fallback_ports == []


def test_fallback_ports_parsed_dedup_and_drop_primary(tmp_path):
    data = {**VALID, "server": {**VALID["server"], "fallback_ports": [8443, 2083, 443, 8443]}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    # primary (443) and duplicates removed, order preserved
    assert cfg.server.fallback_ports == [8443, 2083]
    out = tmp_path / "rt.owcfg"
    cfg.save(out)
    assert json.loads(out.read_text())["server"]["fallback_ports"] == [8443, 2083]


def test_fallback_ports_reject_out_of_range(tmp_path):
    data = {**VALID, "server": {**VALID["server"], "fallback_ports": [70000]}}
    with pytest.raises(ConfigError, match="fallback_ports"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_preshared_key_defaults_empty(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.wireguard.preshared_key == ""


def test_preshared_key_parsed_and_roundtrips(tmp_path):
    data = {**VALID, "wireguard": {**VALID["wireguard"], "preshared_key": "cHNrMDAw"}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.wireguard.preshared_key == "cHNrMDAw"
    out = tmp_path / "rt.owcfg"
    cfg.save(out)
    assert json.loads(out.read_text())["wireguard"]["preshared_key"] == "cHNrMDAw"


def test_expiry_parsed_from_meta(tmp_path):
    data = {**VALID, "meta": {"expires_at": "2030-01-01"}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.expires_at == "2030-01-01"
    assert cfg.is_expired(today="2025-01-01") is False
    assert cfg.is_expired(today="2031-01-01") is True


def test_no_expiry_is_never_expired(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.expires_at == ""
    assert cfg.is_expired(today="2099-01-01") is False


def test_expiry_roundtrips_through_save(tmp_path):
    data = {**VALID, "meta": {"expires_at": "2030-01-01"}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    out = tmp_path / "rt.owcfg"
    cfg.save(out)
    assert json.loads(out.read_text())["meta"]["expires_at"] == "2030-01-01"


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


def test_loads_parses_text():
    cfg = ClientConfig.loads(json.dumps(VALID))
    assert cfg.server.endpoint == "203.0.113.42"


def test_loads_rejects_bad_json():
    with pytest.raises(ConfigError, match="Not valid JSON"):
        ClientConfig.loads("{ not json }")


@pytest.mark.parametrize("payload", ["[]", '"hi"', "42", "null"])
def test_non_object_json_rejected_cleanly(payload):
    # Must raise ConfigError, never a bare AttributeError from raw.get(...).
    with pytest.raises(ConfigError, match="must be a JSON object"):
        ClientConfig.loads(payload)


def test_import_owcfg_text_writes_config_and_original(tmp_path):
    dest = tmp_path / "config.json"
    cfg = import_owcfg_text(json.dumps(VALID), dest)
    assert cfg.server.endpoint == "203.0.113.42"
    assert dest.exists()
    assert original_config_path(dest).exists()
    assert ClientConfig.load(original_config_path(dest)) == ClientConfig.load(dest)


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


def test_hostile_mode_defaults_to_auto_and_roundtrips(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    # Default — even when the .owcfg has no network section.
    assert cfg.network.hostile_mode == "auto"
    # Setting it survives a save/load round-trip.
    patched = apply_profile_patch(cfg, {"hostile_mode": "on"})
    target = tmp_path / "config.json"
    patched.save(target)
    reloaded = ClientConfig.load(target)
    assert reloaded.network.hostile_mode == "on"


def test_hostile_mode_rejects_garbage_values(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    with pytest.raises(ConfigError, match="hostile_mode"):
        apply_profile_patch(cfg, {"hostile_mode": "nope"})


def test_hostile_mode_empty_string_means_auto(tmp_path):
    # Useful when the UI input is cleared — should fall back to auto rather
    # than rejecting it as invalid.
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    patched = apply_profile_patch(cfg, {"hostile_mode": "  "})
    assert patched.network.hostile_mode == "auto"


def test_apply_profile_patch_empty_patch_is_noop(tmp_path):
    cfg = _cfg(tmp_path)
    assert apply_profile_patch(cfg, {}) == cfg


def test_apply_profile_patch_accepts_hostnames_in_bypass(tmp_path):
    # The runtime resolves hostnames at connect time
    # (wireguard._resolve_bypass_networks), so the editor accepts them too.
    cfg = _cfg(tmp_path)
    out = apply_profile_patch(cfg, {
        "bypass_ips": "vpn.example.com, 203.0.113.42, 198.51.100.0/24",
    })
    assert out.routing.bypass_ips == [
        "vpn.example.com", "203.0.113.42", "198.51.100.0/24",
    ]


@pytest.mark.parametrize("patch,match", [
    ({"name": "   "}, "empty"),
    ({"mtu": 99999}, "MTU"),
    ({"mtu": "abc"}, "MTU"),
    ({"dns": "not-an-ip"}, "DNS"),
    ({"client_address": "999.0.0.1/32"}, "client IP"),
    ({"bypass_ips": "bad!host"}, "[Bb]ypass"),
    ({"reconnect_max_attempts": 0}, "[Rr]econnect attempts"),
    ({"reconnect_delays": ""}, "reconnect delay"),
    ({"reconnect_delays": "5, -1"}, "positive"),
])
def test_apply_profile_patch_rejects_bad_input(tmp_path, patch, match):
    with pytest.raises(ConfigError, match=match):
        apply_profile_patch(_cfg(tmp_path), patch)


# --- tls.verify / tls.spki_sha256 (schema v2) ---

SPKI_FP = ":".join(["12"] * 32)


def test_tls_defaults_to_pin_mode(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.tls.verify == "pin"
    assert cfg.tls.spki_sha256 == ""
    assert cfg.tls.pin_value == VALID["tls"]["cert_fingerprint_sha256"]


def test_tls_ca_mode_needs_no_fingerprint(tmp_path):
    data = {**VALID, "schema_version": 2, "tls": {"verify": "ca"}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.tls.verify == "ca"
    assert cfg.tls.cert_fingerprint_sha256 == ""


def test_tls_pin_mode_still_requires_a_pin(tmp_path):
    data = {**VALID, "tls": {}}
    with pytest.raises(ConfigError, match="cert_fingerprint_sha256 or spki_sha256"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_tls_spki_alone_satisfies_pin_mode(tmp_path):
    data = {**VALID, "schema_version": 2, "tls": {"spki_sha256": SPKI_FP}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.tls.pin_value == SPKI_FP


def test_tls_spki_wins_over_cert_fingerprint(tmp_path):
    # Both present is the normal v2 shape: the key pin is the durable one, so
    # it is what the tunnel must actually check.
    data = {**VALID, "schema_version": 2,
            "tls": {**VALID["tls"], "spki_sha256": SPKI_FP}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    assert cfg.tls.pin_value == SPKI_FP


@pytest.mark.parametrize("bad", ["tolerate", "none", "CA-ish", ""])
def test_tls_rejects_unknown_verify_mode(tmp_path, bad):
    data = {**VALID, "tls": {**VALID["tls"], "verify": bad}}
    with pytest.raises(ConfigError, match="tls.verify"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_tls_rejects_malformed_spki(tmp_path):
    data = {**VALID, "tls": {**VALID["tls"], "spki_sha256": "not-a-fingerprint"}}
    with pytest.raises(ConfigError, match="spki_sha256"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_v1_profile_still_loads_under_v2_client(tmp_path):
    # Servers without a key pin keep issuing v1; those profiles must never
    # start failing just because the client learned a newer schema.
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    assert cfg.schema_version == 1


def test_future_schema_version_is_rejected(tmp_path):
    data = {**VALID, "schema_version": 99}
    with pytest.raises(ConfigError, match="Unsupported schema_version 99"):
        ClientConfig.load(write_cfg(tmp_path, data))


def test_v2_tls_round_trips_through_save(tmp_path):
    data = {**VALID, "schema_version": 2,
            "tls": {**VALID["tls"], "verify": "ca", "spki_sha256": SPKI_FP}}
    cfg = ClientConfig.load(write_cfg(tmp_path, data))
    dest = tmp_path / "saved.json"
    cfg.save(dest)
    again = ClientConfig.load(dest)
    assert again.tls == cfg.tls
    assert again.schema_version == 2


def test_v1_profile_round_trip_omits_v2_tls_keys(tmp_path):
    cfg = ClientConfig.load(write_cfg(tmp_path, VALID))
    dest = tmp_path / "saved.json"
    cfg.save(dest)
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert "verify" not in saved["tls"]
    assert "spki_sha256" not in saved["tls"]
