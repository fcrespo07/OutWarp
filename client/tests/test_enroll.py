from __future__ import annotations

import json
import urllib.error
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp.config import (
    ClientConfig,
    EnrollmentConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.enroll import EnrollError, enroll, needs_enrollment

VALID_FP = ":".join(["AB"] * 32)
SPKI_FP = ":".join(["CD"] * 32)


def _cfg(**overrides) -> ClientConfig:
    base = ClientConfig(
        schema_version=3,
        server=ServerConfig(
            endpoint="vpn.example.com", port=443, http_upgrade_path_prefix="s3cret"
        ),
        tls=TlsConfig(cert_fingerprint_sha256=VALID_FP),
        tunnel=TunnelConfig(local_port=51820, remote_host="127.0.0.1", remote_port=51820),
        wireguard=WireguardConfig(
            tunnel_name="OutWarp",
            client_address="10.0.0.2/32",
            client_private_key="",
            server_public_key="srv_pub",
        ),
        routing=RoutingConfig(bypass_ips=["vpn.example.com"]),
        reconnect=ReconnectConfig(),
        enrollment=EnrollmentConfig(
            token="ow_enroll_abc", url="https://vpn.example.com:8444/enroll"
        ),
    )
    return replace(base, **overrides)


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=None)
    return resp


def _http_error(code: int, payload: dict | None = None) -> urllib.error.HTTPError:
    body = json.dumps(payload or {}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://vpn.example.com/enroll", code, "err", {}, BytesIO(body)
    )


class TestNeedsEnrollment:
    def test_true_for_a_fresh_v3_profile(self) -> None:
        assert needs_enrollment(_cfg()) is True

    def test_false_once_a_key_exists(self) -> None:
        cfg = _cfg()
        cfg = replace(cfg, wireguard=replace(cfg.wireguard, client_private_key="priv"))
        assert needs_enrollment(cfg) is False

    def test_false_for_a_legacy_profile(self) -> None:
        cfg = _cfg(enrollment=EnrollmentConfig())
        cfg = replace(cfg, wireguard=replace(cfg.wireguard, client_private_key="priv"))
        assert needs_enrollment(cfg) is False


class TestEnroll:
    def test_posts_only_the_public_key(self) -> None:
        """The whole point: the private half is generated here and must never
        appear in the request."""
        captured: dict = {}

        def _urlopen(req, **_kw):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _response({"ok": True, "client_address": "10.0.0.2/32"})

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen", side_effect=_urlopen),
        ):
            result = enroll(_cfg())

        assert captured["body"] == {"token": "ow_enroll_abc", "client_public_key": "PUB"}
        assert "PRIV" not in json.dumps(captured["body"])
        assert result.wireguard.client_private_key == "PRIV"

    def test_clears_the_spent_token(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True})),
        ):
            result = enroll(_cfg())
        assert result.enrollment.token == ""

    def test_takes_the_address_the_server_reports(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True, "client_address": "10.0.0.9/32"})),
        ):
            result = enroll(_cfg())
        assert result.wireguard.client_address == "10.0.0.9/32"

    def test_pins_the_endpoint_for_a_self_signed_profile(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint") as fp,
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True})),
        ):
            enroll(_cfg())
        fp.assert_called_once_with("vpn.example.com", 8444, VALID_FP)

    def test_prefers_the_key_pin_when_the_profile_has_one(self) -> None:
        cfg = _cfg(tls=TlsConfig(cert_fingerprint_sha256=VALID_FP, spki_sha256=SPKI_FP))
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_spki") as spki,
            patch("outwarp.enroll.verify_tls_fingerprint") as fp,
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True})),
        ):
            enroll(cfg)
        spki.assert_called_once_with("vpn.example.com", 8444, SPKI_FP)
        fp.assert_not_called()

    def test_ca_profile_leaves_verification_to_urlopen(self) -> None:
        cfg = _cfg(tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"))
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint") as fp,
            patch("outwarp.enroll.verify_tls_spki") as spki,
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True})),
        ):
            enroll(cfg)
        fp.assert_not_called()
        spki.assert_not_called()

    def test_refuses_to_enrol_against_a_different_server(self) -> None:
        from outwarp.network import FingerprintMismatchError

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint",
                  side_effect=FingerprintMismatchError("different cert")),
            patch("outwarp.enroll.urllib.request.urlopen") as urlopen,
            pytest.raises(EnrollError, match="not the one"),
        ):
            enroll(_cfg())
        urlopen.assert_not_called()

    def test_surfaces_an_already_used_token(self) -> None:
        """The signal that the profile was intercepted has to reach the user
        verbatim — it is the whole detectability argument for one-time tokens."""
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  side_effect=_http_error(403, {"error": "already redeemed at 12:00Z"})),
            pytest.raises(EnrollError, match="already redeemed"),
        ):
            enroll(_cfg())

    def test_reports_rate_limiting_distinctly(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen", side_effect=_http_error(429)),
            pytest.raises(EnrollError, match="rate-limiting"),
        ):
            enroll(_cfg())

    def test_reports_an_unreachable_endpoint(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  side_effect=urllib.error.URLError("connection refused")),
            pytest.raises(EnrollError, match="Could not reach"),
        ):
            enroll(_cfg())

    def test_reports_a_missing_wg_binary(self) -> None:
        from outwarp.keygen import KeygenError

        with (
            patch("outwarp.enroll.generate_keypair",
                  side_effect=KeygenError("WireGuard tools are required")),
            pytest.raises(EnrollError, match="WireGuard tools"),
        ):
            enroll(_cfg())

    def test_rejects_a_token_without_an_endpoint(self) -> None:
        cfg = _cfg(enrollment=EnrollmentConfig(token="ow_enroll_abc", url=""))
        with pytest.raises(EnrollError, match="no endpoint"):
            enroll(cfg)

    def test_is_a_no_op_for_a_legacy_profile(self) -> None:
        cfg = _cfg(enrollment=EnrollmentConfig())
        cfg = replace(cfg, wireguard=replace(cfg.wireguard, client_private_key="priv"))
        with patch("outwarp.enroll.urllib.request.urlopen") as urlopen:
            assert enroll(cfg) is cfg
        urlopen.assert_not_called()


class TestImportRunsEnrollment:
    def _v3_owcfg(self) -> str:
        return json.dumps({
            "schema_version": 3,
            "name": "laptop",
            "server": {
                "endpoint": "vpn.example.com", "port": 443,
                "http_upgrade_path_prefix": "s3cret",
            },
            "tls": {"cert_fingerprint_sha256": VALID_FP},
            "tunnel": {
                "local_port": 51820, "remote_host": "127.0.0.1", "remote_port": 51820,
            },
            "wireguard": {
                "tunnel_name": "OutWarp",
                "client_address": "10.0.0.2/32",
                "server_public_key": "srv_pub",
            },
            "routing": {"bypass_ips": ["vpn.example.com"]},
            "reconnect": {"max_attempts": 5, "delays_seconds": [5]},
            "enrollment": {
                "token": "ow_enroll_abc",
                "url": "https://vpn.example.com:8444/enroll",
            },
        })

    def test_import_enrols_and_saves_a_usable_profile(self, tmp_path: Path) -> None:
        from outwarp.config import import_owcfg_text

        dest = tmp_path / "config.json"
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  return_value=_response({"ok": True})),
        ):
            cfg = import_owcfg_text(self._v3_owcfg(), dest)

        assert cfg.wireguard.client_private_key == "PRIV"
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert saved["wireguard"]["client_private_key"] == "PRIV"
        assert "enrollment" not in saved

    def test_nothing_is_written_when_enrolment_fails(self, tmp_path: Path) -> None:
        """A half-imported profile with no key would just fail later with a
        worse message; better to leave the previous one alone."""
        from outwarp.config import import_owcfg_text

        dest = tmp_path / "config.json"
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen",
                  side_effect=urllib.error.URLError("down")),
            pytest.raises(EnrollError),
        ):
            import_owcfg_text(self._v3_owcfg(), dest)
        assert not dest.exists()

    def test_enroll_false_parses_without_touching_the_network(self, tmp_path: Path) -> None:
        from outwarp.config import import_owcfg_text

        dest = tmp_path / "config.json"
        # Asserted on keygen rather than urlopen: patching
        # outwarp.enroll.urllib.request.urlopen replaces the *global* urlopen,
        # so a stray call from any other test's background thread would fail
        # this. Key generation is unambiguously part of enrolment and nothing
        # else touches it.
        with patch("outwarp.enroll.generate_keypair") as keygen:
            cfg = import_owcfg_text(self._v3_owcfg(), dest, enroll=False)
        keygen.assert_not_called()
        assert cfg.enrollment.token == "ow_enroll_abc"
        assert cfg.wireguard.client_private_key == ""
