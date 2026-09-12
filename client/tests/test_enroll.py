from __future__ import annotations

import json
import ssl
import urllib.error
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp.config import (
    ClientConfig,
    ConfigError,
    EnrollmentConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.enroll import EnrollError, FingerprintMismatchError, enroll, needs_enrollment

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

    def test_ca_mode_posts_with_a_verifying_tls_context(self) -> None:
        """FIX-02 regression: the enrolment POST used to disable certificate
        verification for *every* https URL, `tls.verify` be damned — so the
        token + client public key travelled unauthenticated in "ca" mode, the
        one where the server is fronted by a real CA-issued cert. The context
        actually handed to urlopen must stay at ssl.create_default_context()'s
        secure defaults in that mode."""
        cfg = _cfg(tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"))
        captured: dict = {}

        def _urlopen(req, context=None, **_kw):
            captured["context"] = context
            return _response({"ok": True})

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.urllib.request.urlopen", side_effect=_urlopen),
        ):
            enroll(cfg)

        ctx = captured["context"]
        assert ctx is not None
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_pin_mode_posts_with_a_relaxed_tls_context(self) -> None:
        """The relaxation is only safe here because _verify_endpoint already
        authenticated the host against the profile's own pin beforehand."""
        captured: dict = {}

        def _urlopen(req, context=None, **_kw):
            captured["context"] = context
            return _response({"ok": True})

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll.urllib.request.urlopen", side_effect=_urlopen),
        ):
            enroll(_cfg())

        ctx = captured["context"]
        assert ctx is not None
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

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
                "server_public_key": "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
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
            # Surfaces as ConfigError (what every import UI already handles),
            # chained from the EnrollError, with a hint about --embed-key.
            pytest.raises(ConfigError, match="embed-key") as excinfo,
        ):
            import_owcfg_text(self._v3_owcfg(), dest)
        assert isinstance(excinfo.value.__cause__, EnrollError)
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


# ── v4: redemption through the tunnel port ────────────────────────────────────

class _EnrollStub:
    """A loopback HTTP server standing in for the far end of the forward."""

    def __init__(self, handler) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        stub = self

        class _H(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                stub.requests.append((self.path, body))
                status, payload = handler(body)
                out = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.requests: list = []
        self._httpd = HTTPServer(("127.0.0.1", 0), _H)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _v4_cfg(**overrides) -> ClientConfig:
    return _cfg(
        schema_version=4,
        enrollment=EnrollmentConfig(token="ow_enroll_abc", remote_port=8444),
        **overrides,
    )


@pytest.fixture
def stub():
    s = _EnrollStub(lambda body: (200, {"ok": True, "client_address": "10.0.0.7/32"}))
    try:
        yield s
    finally:
        s.close()


def _forward_to(port: int, attempts: list | None = None):
    """Replacement for _open_forward: record the rung, yield the stub's port."""
    import contextlib

    @contextlib.contextmanager
    def _fake(config, rung, wstunnel_bin):
        if attempts is not None:
            attempts.append(rung.id)
        yield port

    return _fake


class TestEnrolViaTransport:
    def test_posts_through_the_forward_and_pins_the_tunnel_port_first(self, stub) -> None:
        """B-018: no public enrolment port. The token goes over a wstunnel TCP
        forward on `server.port`, to a plain-HTTP loopback listener."""
        rungs: list[str] = []
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.tunnel.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
            patch("outwarp.enroll.verify_tls_fingerprint") as fp,
            patch("outwarp.enroll._open_forward", _forward_to(stub.port, rungs)),
        ):
            result = enroll(_v4_cfg())

        assert rungs == ["direct"]
        fp.assert_called_once_with("vpn.example.com", 443, VALID_FP)
        assert stub.requests == [
            ("/enroll", {"token": "ow_enroll_abc", "client_public_key": "PUB"}),
        ]
        assert result.wireguard.client_private_key == "PRIV"
        assert result.wireguard.client_address == "10.0.0.7/32"
        assert result.enrollment == EnrollmentConfig()

    def test_walks_the_ladder_when_the_first_rung_cannot_carry_it(self, stub) -> None:
        """Same rungs as the tunnel: a network that needs the public-DNS
        rung to connect must be able to enrol on it too."""
        import contextlib

        rungs: list[str] = []

        @contextlib.contextmanager
        def _flaky(config, rung, wstunnel_bin):
            rungs.append(rung.id)
            if rung.id == "direct":
                raise EnrollError("wstunnel did not open its local forward port in time")
            yield stub.port

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.tunnel.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll._open_forward", _flaky),
        ):
            result = enroll(_v4_cfg())

        assert rungs == ["direct", "direct-hostile"]
        assert result.wireguard.client_private_key == "PRIV"

    def test_a_refusal_from_the_server_stops_the_ladder(self) -> None:
        """The server answered — the token is spent or wrong. Retrying on
        another rung cannot change that and would only burn attempts."""
        s = _EnrollStub(lambda body: (403, {"error": "token already redeemed"}))
        rungs: list[str] = []
        try:
            with (
                patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
                patch("outwarp.tunnel.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
                patch("outwarp.enroll.verify_tls_fingerprint"),
                patch("outwarp.enroll._open_forward", _forward_to(s.port, rungs)),
                pytest.raises(EnrollError, match="already redeemed"),
            ):
                enroll(_v4_cfg())
        finally:
            s.close()
        assert rungs == ["direct"]

    def test_a_pin_mismatch_stops_the_ladder(self) -> None:
        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.tunnel.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
            patch("outwarp.enroll.verify_tls_fingerprint",
                  side_effect=FingerprintMismatchError("expected X got Y")),
            patch("outwarp.enroll._open_forward") as fwd,
            pytest.raises(EnrollError, match="not the one this profile was issued for"),
        ):
            enroll(_v4_cfg())
        fwd.assert_not_called()

    def test_reports_every_rung_when_none_carries_it(self) -> None:
        import contextlib

        @contextlib.contextmanager
        def _dead(config, rung, wstunnel_bin):
            raise EnrollError("wstunnel exited before opening its local port (code 1)")
            yield  # pragma: no cover

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.tunnel.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
            patch("outwarp.enroll.verify_tls_fingerprint"),
            patch("outwarp.enroll._open_forward", _dead),
            pytest.raises(EnrollError, match="through the tunnel port") as info,
        ):
            enroll(_v4_cfg())
        assert "Direct:" in str(info.value)
        assert "Direct (public DNS):" in str(info.value)

    def test_ca_profile_lets_wstunnel_verify_the_chain(self) -> None:
        from outwarp.enroll import _forward_command
        from outwarp.fallback import build_ladder

        cfg = _v4_cfg(tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"))
        rung = build_ladder(cfg)[0]
        wstunnel = Path("/usr/bin/wstunnel")
        cmd = _forward_command(rung, wstunnel, 40001, 8444)
        # str(Path) is backslashed on Windows; compare through Path.
        assert cmd[:2] == [str(wstunnel), "client"]
        assert "tcp://127.0.0.1:40001:127.0.0.1:8444" in cmd
        assert "--tls-verify-certificate" in cmd
        assert cmd[cmd.index("--http-upgrade-path-prefix") + 1] == "s3cret"
        assert cmd[-1] == "wss://vpn.example.com"

    def test_forward_gives_up_when_wstunnel_dies(self) -> None:
        from outwarp.enroll import _wait_for_local_port

        dead = MagicMock()
        dead.poll.return_value = 1
        dead.returncode = 1
        with pytest.raises(EnrollError, match="exited before opening"):
            _wait_for_local_port(dead, 1)

    def test_missing_wstunnel_is_reported_not_raised_raw(self) -> None:
        from outwarp.tunnel import TunnelError

        with (
            patch("outwarp.enroll.generate_keypair", return_value=("PRIV", "PUB")),
            patch("outwarp.tunnel.find_wstunnel",
                  side_effect=TunnelError("wstunnel binary not found")),
            pytest.raises(EnrollError, match="wstunnel binary not found"),
        ):
            enroll(_v4_cfg())
