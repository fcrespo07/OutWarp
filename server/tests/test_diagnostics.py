from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from outwarp_server import diagnostics
from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.diagnostics import (
    CheckResult,
    Status,
    check_clients_registered,
    check_config_loadable,
    check_egress,
    check_tls_cert_files,
    check_win_netnat,
    check_win_winnat_service,
    run_all,
)


def _make_config(tmp_path: Path, **overrides: object) -> ServerConfig:
    cert = tmp_path / "server_cert.pem"
    key = tmp_path / "server_key.pem"
    defaults = dict(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="s3cr3t",
        cert_path=str(cert),
        key_path=str(key),
        cert_fingerprint_sha256="AB:CD" * 16,
        wg_private_key="srv_priv",
        wg_public_key="srv_pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=[],
    )
    defaults.update(overrides)
    return ServerConfig(**defaults)  # type: ignore[arg-type]


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ───────── common checks ─────────

class TestConfigLoadable:
    def test_passes(self, tmp_path: Path) -> None:
        r = check_config_loadable(_make_config(tmp_path))
        assert r.status is Status.PASS
        assert "203.0.113.42:443" in r.detail


class TestClientsRegistered:
    def test_warns_when_empty(self, tmp_path: Path) -> None:
        r = check_clients_registered(_make_config(tmp_path))
        assert r.status is Status.WARN
        assert "add-client" in (r.remediation or "")

    def test_passes_with_clients(self, tmp_path: Path) -> None:
        c = ClientEntry(name="laptop", public_key="abc", address="10.0.0.2/32")
        r = check_clients_registered(_make_config(tmp_path, clients=[c]))
        assert r.status is Status.PASS
        assert "1 client" in r.detail


class TestTlsCertFiles:
    def test_fails_when_missing(self, tmp_path: Path) -> None:
        r = check_tls_cert_files(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "server_cert.pem" in r.detail

    def test_passes_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "server_cert.pem").write_text("cert")
        (tmp_path / "server_key.pem").write_text("key")
        r = check_tls_cert_files(_make_config(tmp_path))
        assert r.status is Status.PASS


class TestEgress:
    def test_passes_when_socket_connects(self, tmp_path: Path) -> None:
        fake_sock = MagicMock()
        fake_sock.__enter__ = MagicMock(return_value=fake_sock)
        fake_sock.__exit__ = MagicMock(return_value=False)
        with patch("outwarp_server.diagnostics.socket.create_connection", return_value=fake_sock):
            r = check_egress(_make_config(tmp_path))
        assert r.status is Status.PASS

    def test_fails_when_unreachable(self, tmp_path: Path) -> None:
        with patch(
            "outwarp_server.diagnostics.socket.create_connection",
            side_effect=TimeoutError("timed out"),
        ):
            r = check_egress(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "1.1.1.1:443" in r.detail


# ───────── Windows NetNat parsing (the meaty one) ─────────

class TestWinNetNat:
    def _patch_ps(self, raw: str):
        return patch.object(diagnostics, "_ps", return_value=_completed(stdout=raw))

    def test_no_nats_at_all(self, tmp_path: Path) -> None:
        with self._patch_ps(""):
            r = check_win_netnat(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "No NetNat instances" in r.detail
        assert "New-NetNat" in (r.remediation or "")

    def test_matching_nat_active(self, tmp_path: Path) -> None:
        raw = json.dumps({
            "Name": "OutWarp",
            "InternalIPInterfaceAddressPrefix": "10.0.0.0/24",
            "Active": True,
        })
        with self._patch_ps(raw):
            r = check_win_netnat(_make_config(tmp_path))
        assert r.status is Status.PASS
        assert "OutWarp" in r.detail

    def test_conflicting_nat_only(self, tmp_path: Path) -> None:
        # The headline scenario: WSL/Hyper-V created a NetNat first, so ours
        # was silently rejected.
        raw = json.dumps({
            "Name": "WSL",
            "InternalIPInterfaceAddressPrefix": "172.20.0.0/20",
            "Active": True,
        })
        with self._patch_ps(raw):
            r = check_win_netnat(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "No NetNat covers 10.0.0.0/24" in r.detail
        assert "WSL" in r.detail
        assert "Remove-NetNat" in (r.remediation or "")

    def test_matching_nat_but_others_present(self, tmp_path: Path) -> None:
        raw = json.dumps([
            {"Name": "OutWarp", "InternalIPInterfaceAddressPrefix": "10.0.0.0/24", "Active": True},
            {"Name": "WSL", "InternalIPInterfaceAddressPrefix": "172.20.0.0/20", "Active": True},
        ])
        with self._patch_ps(raw):
            r = check_win_netnat(_make_config(tmp_path))
        assert r.status is Status.WARN
        assert "additional NetNats" in r.detail

    def test_nat_inactive(self, tmp_path: Path) -> None:
        raw = json.dumps({
            "Name": "OutWarp",
            "InternalIPInterfaceAddressPrefix": "10.0.0.0/24",
            "Active": False,
        })
        with self._patch_ps(raw):
            r = check_win_netnat(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "Active=False" in r.detail
        assert "Restart-Service WinNat" in (r.remediation or "")


class TestWinNatService:
    def test_running(self, tmp_path: Path) -> None:
        with patch.object(diagnostics, "_sc", return_value=_completed("STATE : 4 RUNNING")):
            r = check_win_winnat_service(_make_config(tmp_path))
        assert r.status is Status.PASS

    def test_stopped(self, tmp_path: Path) -> None:
        with patch.object(diagnostics, "_sc", return_value=_completed("STATE : 1 STOPPED")):
            r = check_win_winnat_service(_make_config(tmp_path))
        assert r.status is Status.FAIL
        assert "Start-Service WinNat" in (r.remediation or "")


# ───────── orchestration ─────────

class TestRunAll:
    def test_captures_check_exceptions(self, tmp_path: Path) -> None:
        # If a check crashes, run_all must not let the exception bubble — it
        # should record a FAIL result with the exception message instead.
        cfg = _make_config(tmp_path)
        boom = diagnostics.Check(
            "boom", "Test", lambda c: (_ for _ in ()).throw(RuntimeError("kaboom"))
        )
        with patch.object(diagnostics, "gather_checks", return_value=[boom]):
            results = run_all(cfg)
        assert len(results) == 1
        assert results[0].status is Status.FAIL
        assert "kaboom" in results[0].detail

    def test_returns_one_result_per_check(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        ok = diagnostics.Check("ok", "Test", lambda c: CheckResult("ok", Status.PASS))
        with patch.object(diagnostics, "gather_checks", return_value=[ok, ok, ok]):
            results = run_all(cfg)
        assert [r.status for r in results] == [Status.PASS] * 3


# ───────── transport branch (domain / Caddy) ─────────

class TestCaddyFrontCheck:
    def test_skipped_in_self_signed_mode(self, tmp_path: Path) -> None:
        r = diagnostics.check_caddy_front(_make_config(tmp_path))
        assert r.status is diagnostics.Status.SKIP

    def test_fails_when_caddy_is_not_installed(self, tmp_path: Path) -> None:
        from outwarp_server import caddy

        cfg = _make_config(tmp_path, tls_mode="acme")
        with patch.object(caddy, "find_caddy", return_value=None):
            r = diagnostics.check_caddy_front(cfg)
        assert r.status is diagnostics.Status.FAIL
        assert r.fix_kind == "interactive"

    def test_fails_when_the_site_config_is_missing(self, tmp_path: Path) -> None:
        from outwarp_server import caddy

        cfg = _make_config(tmp_path, tls_mode="acme")
        with (
            patch.object(caddy, "find_caddy", return_value=Path("/usr/bin/caddy")),
            patch.object(caddy, "CADDY_SITE_FILE", tmp_path / "missing.caddyfile"),
        ):
            r = diagnostics.check_caddy_front(cfg)
        assert r.status is diagnostics.Status.FAIL
        assert "missing" in r.detail

    def test_passes_when_the_config_validates(self, tmp_path: Path) -> None:
        from outwarp_server import caddy

        site = tmp_path / "outwarp.caddyfile"
        site.write_text("x", encoding="utf-8")
        cfg = _make_config(tmp_path, tls_mode="acme")
        with (
            patch.object(caddy, "find_caddy", return_value=Path("/usr/bin/caddy")),
            patch.object(caddy, "CADDY_SITE_FILE", site),
            patch.object(caddy, "validate", return_value=(True, "")),
        ):
            r = diagnostics.check_caddy_front(cfg)
        assert r.status is diagnostics.Status.PASS


class TestPublicCertificateCheck:
    def test_skipped_in_self_signed_mode(self, tmp_path: Path) -> None:
        r = diagnostics.check_public_certificate(_make_config(tmp_path))
        assert r.status is diagnostics.Status.SKIP

    def test_fails_on_an_untrusted_chain(self, tmp_path: Path) -> None:
        import ssl

        exc = ssl.SSLCertVerificationError("unable to get local issuer certificate")
        exc.verify_message = "unable to get local issuer certificate"
        ctx = MagicMock()
        ctx.wrap_socket.side_effect = exc
        cfg = _make_config(tmp_path, tls_mode="acme", endpoint="vpn.example.com")
        with (
            patch("ssl.create_default_context", return_value=ctx),
            patch("outwarp_server.diagnostics.socket.create_connection",
                  return_value=MagicMock()),
        ):
            r = diagnostics.check_public_certificate(cfg)
        assert r.status is diagnostics.Status.FAIL

    def test_only_warns_when_the_endpoint_is_unreachable(self, tmp_path: Path) -> None:
        # Hairpin NAT routinely stops a server reaching its own public name;
        # that is not evidence the certificate is broken.
        cfg = _make_config(tmp_path, tls_mode="acme", endpoint="vpn.example.com")
        with patch("outwarp_server.diagnostics.socket.create_connection",
                   side_effect=OSError("no route")):
            r = diagnostics.check_public_certificate(cfg)
        assert r.status is diagnostics.Status.WARN
