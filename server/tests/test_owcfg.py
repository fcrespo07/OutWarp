from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits not enforced on NTFS")
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


# Real-shaped fake keys (44-char base64, valid WireGuard key encoding) — the
# client's parser validates wireguard.* fields (FIX-01), so these two
# cross-package round-trip tests need values that actually pass, unlike the
# rest of this file's placeholders which never reach that parser.
_CLIENT_PRIV = "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c="
_SERVER_PUB = "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE="
_PSK = "rY2vuEB4VDipfXtL8xlnizgU9eBsI2tQfKw7L4xLFIw="


def test_psk_and_expiry_roundtrip_to_client(tmp_path: Path) -> None:
    try:
        from outwarp.config import ClientConfig
    except ImportError:
        import pytest
        pytest.skip("Client package not installed in this environment")

    from dataclasses import replace

    server_config = replace(_make_server_config(), wg_public_key=_SERVER_PUB)
    cfg = build_owcfg(
        server_config, "laptop", _CLIENT_PRIV, "10.0.0.2/32",
        preshared_key=_PSK, expires_at="2030-01-01",
    )
    out = tmp_path / "laptop.owcfg"
    write_owcfg(cfg, out)
    client_cfg = ClientConfig.load(out)
    assert client_cfg.wireguard.preshared_key == _PSK
    assert client_cfg.expires_at == "2030-01-01"


def test_warpcfg_compatible_with_client_schema(tmp_path: Path) -> None:
    """Verify the .owcfg can be loaded by the client's ClientConfig parser."""
    # This import works because the client package is installed in the same venv
    try:
        from outwarp.config import ClientConfig
    except ImportError:
        import pytest
        pytest.skip("Client package not installed in this environment")

    from dataclasses import replace

    server_config = replace(_make_server_config(), wg_public_key=_SERVER_PUB)
    cfg = build_owcfg(server_config, "laptop", _CLIENT_PRIV, "10.0.0.2/32")
    out = tmp_path / "laptop.owcfg"
    write_owcfg(cfg, out)
    client_cfg = ClientConfig.load(out)
    assert client_cfg.server.endpoint == "203.0.113.42"
    assert client_cfg.wireguard.client_private_key == _CLIENT_PRIV


# --- key pin (schema v2) ---

SPKI = ":".join(["7F"] * 32)


def test_owcfg_stays_v1_without_a_key_pin() -> None:
    """A server set up before spki_sha256 existed keeps issuing v1 profiles, so
    clients that predate the field are not locked out by an upgrade."""
    cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
    assert cfg["schema_version"] == 1
    assert "spki_sha256" not in cfg["tls"]


def test_owcfg_carries_the_key_pin_and_bumps_the_schema() -> None:
    from dataclasses import replace

    server = replace(_make_server_config(), spki_sha256=SPKI)
    cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")
    # The bump is required, not cosmetic: a v1 client would ignore the field
    # and keep pinning the certificate, which renew-cert then invalidates.
    assert cfg["schema_version"] == 2
    assert cfg["tls"]["spki_sha256"] == SPKI
    assert cfg["tls"]["cert_fingerprint_sha256"] == server.cert_fingerprint_sha256


# --- domain branch: CA validation instead of a pin ---

def test_acme_profile_validates_the_chain_and_carries_no_pin() -> None:
    """Behind Caddy the certificate renews every ~60 days. Pinning it would
    break every distributed profile at the first renewal, so the profile asks
    the client to validate against the system CA store instead."""
    from dataclasses import replace

    server = replace(_make_server_config(), tls_mode="acme", endpoint="vpn.example.com")
    cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")

    assert cfg["schema_version"] == 2
    assert cfg["tls"] == {"verify": "ca"}
    assert cfg["server"]["endpoint"] == "vpn.example.com"


def test_acme_profile_ignores_a_stale_self_signed_pin() -> None:
    # The internal self-signed cert still exists (the web panel uses it); it
    # just has nothing to do with what the client will see on the wire.
    from dataclasses import replace

    server = replace(_make_server_config(), tls_mode="acme", spki_sha256=SPKI)
    cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")
    assert "spki_sha256" not in cfg["tls"]
    assert "cert_fingerprint_sha256" not in cfg["tls"]


# --- .owcfg signing (CONCEPTO-C prop.2) ---

class TestOwcfgSigning:
    def _signed_server_config(self):
        from dataclasses import replace

        from outwarp_server import minisign

        key_id, private_key, public_key = minisign.generate_keypair()
        return replace(
            _make_server_config(),
            owcfg_signing_key_id=key_id.hex(),
            owcfg_signing_private_key=base64.b64encode(private_key).decode(),
            owcfg_signing_public_key=minisign.format_public_key(key_id, public_key),
        )

    def test_unsigned_when_server_has_no_signing_key(self) -> None:
        cfg = build_owcfg(_make_server_config(), "laptop", "client_priv", "10.0.0.2/32")
        assert "signing" not in cfg

    def test_signed_profile_verifies_against_its_own_embedded_key(self) -> None:
        from outwarp_server import minisign
        from outwarp_server.owcfg import _canonical_json

        server = self._signed_server_config()
        cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")

        assert "signing" in cfg
        signing = cfg.pop("signing")
        minisign.verify(_canonical_json(cfg), signing["signature"], signing["public_key"])

    def test_tampered_field_breaks_the_signature(self) -> None:
        from outwarp_server import minisign
        from outwarp_server.owcfg import _canonical_json

        server = self._signed_server_config()
        cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")
        signing = cfg.pop("signing")

        cfg["server"]["endpoint"] = "evil.attacker.example"  # tampered post-signing
        with pytest.raises(minisign.MinisignError):
            minisign.verify(_canonical_json(cfg), signing["signature"], signing["public_key"])

    def test_signature_binds_to_the_client_name(self) -> None:
        """A signature valid for 'laptop' must not verify for a re-labelled
        copy of the same profile content — the trusted comment binds the name."""
        from outwarp_server import minisign
        from outwarp_server.owcfg import _canonical_json

        server = self._signed_server_config()
        cfg = build_owcfg(server, "laptop", "client_priv", "10.0.0.2/32")
        signing = cfg.pop("signing")

        cfg["name"] = "phone"
        with pytest.raises(minisign.MinisignError):
            minisign.verify(_canonical_json(cfg), signing["signature"], signing["public_key"])


class TestEnsureOwcfgSigningKey:
    def test_generates_a_key_when_missing(self) -> None:
        from outwarp_server.operations import _ensure_owcfg_signing_key

        updated = _ensure_owcfg_signing_key(_make_server_config())
        assert updated.owcfg_signing_key_id
        assert updated.owcfg_signing_private_key
        assert updated.owcfg_signing_public_key.startswith("untrusted comment:")

    def test_does_not_regenerate_an_existing_key(self) -> None:
        from dataclasses import replace

        from outwarp_server.operations import _ensure_owcfg_signing_key

        server = replace(_make_server_config(), owcfg_signing_private_key="existing-key-material")
        updated = _ensure_owcfg_signing_key(server)
        assert updated is server


class TestEnrolmentProfile:
    def test_v4_redeems_through_the_tunnel_port(self) -> None:
        """B-018: v3 carried a public HTTPS URL on a second port (8444) that
        no home router forwards. v4 carries only the server-side loopback port
        the client reaches as a wstunnel forward over `server.port`."""
        owcfg = build_owcfg(
            _make_server_config(), "laptop", "", "10.0.0.2/32",
            enrollment_token="ow_enroll_abc",
        )
        assert owcfg["schema_version"] == 4
        assert owcfg["enrollment"] == {"token": "ow_enroll_abc", "remote_port": 8444}
        assert "client_private_key" not in owcfg["wireguard"]

    def test_v4_in_the_acme_branch_too(self) -> None:
        """One mechanism for both branches: behind Caddy the forward rides
        the same WebSocket, so no per-branch URL is needed."""
        from dataclasses import replace

        cfg = replace(_make_server_config(), tls_mode="acme", enroll_port=9000)
        owcfg = build_owcfg(cfg, "laptop", "", "10.0.0.2/32", enrollment_token="ow_enroll_abc")
        assert owcfg["schema_version"] == 4
        assert owcfg["enrollment"] == {"token": "ow_enroll_abc", "remote_port": 9000}
        assert owcfg["tls"] == {"verify": "ca"}
