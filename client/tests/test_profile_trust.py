from __future__ import annotations

import copy
import json

import pytest

from outwarp import profile_trust
from outwarp.config import ConfigError, import_owcfg_text

VALID = {
    "schema_version": 1,
    "name": "laptop",
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
        "client_private_key": "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
        "server_public_key": "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
    "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
}


def _signed(raw: dict) -> dict:
    """Sign `raw` with a fresh real server keypair (outwarp_server.minisign),
    matching exactly what a real server issuing a profile would produce."""
    try:
        from outwarp_server import minisign as server_minisign
    except ImportError:
        pytest.skip("Server package not installed in this environment")

    key_id, private_key, public_key = server_minisign.generate_keypair()
    pub_text = server_minisign.format_public_key(key_id, public_key)
    payload = profile_trust.canonical_json(raw)
    sig_text = server_minisign.sign(
        payload, key_id, private_key, trusted_comment=f"OutWarp profile for {raw['name']}"
    )
    return {**raw, "signing": {"public_key": pub_text, "signature": sig_text}}


# --- verify_and_pin ---

def test_no_signing_block_warns_and_does_not_raise(tmp_path):
    store = tmp_path / "known_servers.json"
    profile_trust.verify_and_pin(copy.deepcopy(VALID), path=store)  # must not raise
    assert not store.exists()


def test_non_dict_input_is_a_noop():
    profile_trust.verify_and_pin([1, 2, 3])  # must not raise
    profile_trust.verify_and_pin("not a dict")  # must not raise


def test_valid_signature_pins_the_key(tmp_path):
    store = tmp_path / "known_servers.json"
    signed = _signed(copy.deepcopy(VALID))

    profile_trust.verify_and_pin(signed, path=store)

    pinned = json.loads(store.read_text(encoding="utf-8"))
    assert pinned["203.0.113.42"] == signed["signing"]["public_key"]


def test_tampered_field_is_rejected(tmp_path):
    store = tmp_path / "known_servers.json"
    signed = _signed(copy.deepcopy(VALID))
    signed["server"]["endpoint"] = "evil.attacker.example"  # tampered post-signing

    with pytest.raises(profile_trust.ProfileTrustError, match="invalid"):
        profile_trust.verify_and_pin(signed, path=store)
    assert not store.exists()


def test_malformed_signing_block_is_rejected(tmp_path):
    store = tmp_path / "known_servers.json"
    bad = {**VALID, "signing": {"public_key": "not-minisign-text"}}  # missing signature
    with pytest.raises(profile_trust.ProfileTrustError, match="missing"):
        profile_trust.verify_and_pin(bad, path=store)


def test_same_key_on_repeat_import_does_not_warn_or_change_the_pin(tmp_path, caplog):
    store = tmp_path / "known_servers.json"
    signed = _signed(copy.deepcopy(VALID))
    profile_trust.verify_and_pin(signed, path=store)

    caplog.clear()
    with caplog.at_level("WARNING"):
        profile_trust.verify_and_pin(signed, path=store)
    assert not any("different key" in r.message for r in caplog.records)
    pinned = json.loads(store.read_text(encoding="utf-8"))
    assert pinned["203.0.113.42"] == signed["signing"]["public_key"]


def test_different_key_for_a_known_endpoint_warns_but_keeps_the_old_pin(tmp_path, caplog):
    """Detects an unannounced key rotation / possible impersonation, without
    hard-blocking a legitimate one — see the module docstring."""
    store = tmp_path / "known_servers.json"
    first = _signed(copy.deepcopy(VALID))
    profile_trust.verify_and_pin(first, path=store)
    original_pin = json.loads(store.read_text(encoding="utf-8"))["203.0.113.42"]

    second = _signed(copy.deepcopy(VALID))  # fresh keypair -> different public_key
    with caplog.at_level("WARNING"):
        profile_trust.verify_and_pin(second, path=store)
    assert any("different key" in r.message for r in caplog.records)
    assert json.loads(store.read_text(encoding="utf-8"))["203.0.113.42"] == original_pin


# --- end-to-end through import_owcfg_text ---

def test_import_accepts_a_validly_signed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_trust, "known_servers_path", lambda: tmp_path / "known.json")
    signed = _signed(copy.deepcopy(VALID))
    cfg = import_owcfg_text(json.dumps(signed), tmp_path / "config.json", enroll=False)
    assert cfg.server.endpoint == "203.0.113.42"


def test_import_refuses_a_tampered_signed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_trust, "known_servers_path", lambda: tmp_path / "known.json")
    signed = _signed(copy.deepcopy(VALID))
    signed["wireguard"]["server_public_key"] = "eY7+WjKbAd6NrjDOJb7LaSSd8WQHl0BszTY9yzKoGyA="
    with pytest.raises(ConfigError, match="invalid"):
        import_owcfg_text(json.dumps(signed), tmp_path / "config.json", enroll=False)
    assert not (tmp_path / "config.json").exists()


def test_unsigned_profile_for_a_pinned_endpoint_is_rejected(tmp_path):
    """Regression: once a server's key is pinned, an unsigned profile for the
    same endpoint used to import with only a log warning — stripping the
    `signing` block off a tampered profile bypassed the pin entirely."""
    store = tmp_path / "known_servers.json"
    profile_trust.verify_and_pin(_signed(copy.deepcopy(VALID)), path=store)
    assert store.exists()

    with pytest.raises(profile_trust.ProfileTrustError, match="unsigned"):
        profile_trust.verify_and_pin(copy.deepcopy(VALID), path=store)


def test_unsigned_profile_for_an_unknown_endpoint_still_imports(tmp_path):
    """The fail-open path stays for servers never seen signing (0.11 servers)."""
    store = tmp_path / "known_servers.json"
    other = copy.deepcopy(VALID)
    other["server"]["endpoint"] = "198.51.100.7"
    profile_trust.verify_and_pin(_signed(copy.deepcopy(VALID)), path=store)
    profile_trust.verify_and_pin(other, path=store)  # must not raise
