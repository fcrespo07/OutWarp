from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server import diagnostics
from outwarp_server.config import ServerConfig
from outwarp_server.diagnostics import Status


def _config(**overrides) -> ServerConfig:
    base = dict(
        schema_version=1,
        endpoint="vpn.example.com",
        port=443,
        http_upgrade_path_prefix="x",
        cert_path="/tmp/cert.pem",
        key_path="/tmp/key.pem",
        cert_fingerprint_sha256="AB:" * 31 + "AB",
        wg_private_key="p",
        wg_public_key="P",
        subnet="10.13.13.0/24",
        server_address="10.13.13.1/24",
        wg_listen_port=51820,
        clients=[],
    )
    base.update(overrides)
    return ServerConfig(**base)


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = stderr
    return proc


class TestBinaries:
    def test_pass_when_both_present(self) -> None:
        with (
            patch(
                "outwarp_server.diagnostics.shutil.which",
                side_effect=lambda b: f"/usr/bin/{b}",
            ),
            patch(
                "outwarp_server.diagnostics._run_linux",
                return_value=_completed("wireguard-tools v1.0\n"),
            ),
        ):
            r = diagnostics.check_linux_binaries(_config())
        assert r.status is Status.PASS

    def test_fail_when_both_missing(self) -> None:
        with patch("outwarp_server.diagnostics.shutil.which", return_value=None):
            r = diagnostics.check_linux_binaries(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "interactive"


class TestKmod:
    def test_pass_when_modinfo_returns_zero(self) -> None:
        with patch(
            "outwarp_server.diagnostics._run_linux",
            return_value=_completed("filename: /lib/modules/.../wireguard.ko\n"),
        ):
            r = diagnostics.check_linux_kmod(_config())
        assert r.status is Status.PASS

    def test_fail_when_modinfo_returns_nonzero(self) -> None:
        with patch(
            "outwarp_server.diagnostics._run_linux",
            return_value=_completed("", returncode=1),
        ):
            r = diagnostics.check_linux_kmod(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "interactive"

    def test_pass_via_interface_when_modinfo_missing(self) -> None:
        """Container image: no modinfo on PATH, but the node's wg0 is up."""
        with patch(
            "outwarp_server.diagnostics._run_linux",
            side_effect=[FileNotFoundError(), _completed("5: wg0: <POINTOPOINT>\n")],
        ):
            r = diagnostics.check_linux_kmod(_config())
        assert r.status is Status.PASS
        assert "container" in r.detail

    def test_fail_when_modinfo_missing_and_no_interface(self) -> None:
        with patch(
            "outwarp_server.diagnostics._run_linux",
            side_effect=[FileNotFoundError(), _completed("", returncode=1)],
        ):
            r = diagnostics.check_linux_kmod(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "manual"


class TestSystemd:
    def test_pass_when_all_active(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch(
                "outwarp_server.diagnostics._run_linux",
                return_value=_completed("active\n"),
            ),
        ):
            r = diagnostics.check_linux_systemd(_config())
        assert r.status is Status.PASS

    def test_fail_includes_fix_callable(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._enroll_unit_installed", return_value=True),
            patch(
                "outwarp_server.diagnostics._run_linux",
                return_value=_completed("inactive\n"),
            ),
        ):
            r = diagnostics.check_linux_systemd(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "auto"
        assert callable(r.fix_callable)

    def test_checks_the_enrolment_unit_too(self) -> None:
        """B-018: a systemd install had no process running the enrolment
        listener at all, so every enrolment profile was dead on arrival while
        doctor reported all green. The unit is now part of the set."""
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._enroll_unit_installed", return_value=True),
            patch(
                "outwarp_server.diagnostics._run_linux",
                return_value=_completed("active\n"),
            ) as run,
        ):
            r = diagnostics.check_linux_systemd(_config())
        assert r.status is Status.PASS
        queried = [call.args[0][-1] for call in run.call_args_list]
        assert "outwarp-enroll.service" in queried

    def test_missing_enrolment_unit_points_at_restart_not_systemctl(self) -> None:
        """Upgrading from < 0.13 leaves no outwarp-enroll.service on disk;
        `systemctl restart` of a unit that does not exist is a dead end, so
        the remediation is the command that (re)writes every unit."""
        def _is_active(cmd, timeout=5.0):
            return _completed("inactive\n" if "enroll" in cmd[-1] else "active\n")

        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._enroll_unit_installed", return_value=False),
            patch("outwarp_server.diagnostics._run_linux", side_effect=_is_active),
        ):
            r = diagnostics.check_linux_systemd(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "manual"
        assert r.remediation_command == "outwarp-server restart"

    def test_skip_when_no_systemd(self) -> None:
        """Container (Docker/K8s): no systemd, wstunnel/WireGuard supervised
        directly — this check doesn't apply, and mustn't crash trying to run
        a missing `systemctl`."""
        with patch("outwarp_server.diagnostics._has_systemd", return_value=False):
            r = diagnostics.check_linux_systemd(_config())
        assert r.status is Status.SKIP


class TestListen443:
    def test_pass_when_port_bound(self) -> None:
        ss_out = (
            "State    Recv-Q  Send-Q  Local        Peer\n"
            "LISTEN   0       128     0.0.0.0:443  0.0.0.0:*\n"
        )
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed(ss_out)):
            r = diagnostics.check_linux_listen_443(_config())
        assert r.status is Status.PASS

    def test_fail_when_port_idle(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._run_linux", return_value=_completed("State\n")),
        ):
            r = diagnostics.check_linux_listen_443(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "auto"

    def test_fail_when_port_idle_and_no_systemd(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=False),
            patch("outwarp_server.diagnostics._run_linux", return_value=_completed("State\n")),
        ):
            r = diagnostics.check_linux_listen_443(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "manual"
        assert "kubectl" in r.remediation_command


class TestListenWg:
    def test_pass_when_bound_to_loopback(self) -> None:
        out = "State\nUNCONN  0  0  127.0.0.1:51820  *:*\n"
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed(out)):
            r = diagnostics.check_linux_listen_wg(_config())
        assert r.status is Status.PASS

    def test_fail_when_bound_publicly(self) -> None:
        out = "State\nUNCONN  0  0  0.0.0.0:51820  *:*\n"
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._run_linux", return_value=_completed(out)),
        ):
            r = diagnostics.check_linux_listen_wg(_config())
        assert r.status is Status.FAIL

    def test_warn_when_bound_publicly_and_no_systemd(self) -> None:
        """Kernel WireGuard under KubernetesServerPlatform always binds every
        interface — that's unfixable via `outwarp-server restart`, so it's a
        WARN with a firewall pointer instead of a dead-end FAIL there."""
        out = "State\nUNCONN  0  0  0.0.0.0:51820  *:*\n"
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=False),
            patch("outwarp_server.diagnostics._run_linux", return_value=_completed(out)),
        ):
            r = diagnostics.check_linux_listen_wg(_config())
        assert r.status is Status.WARN
        assert r.fix_kind == "manual"

    def test_warn_when_no_listener_yet(self) -> None:
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed("State\n")):
            r = diagnostics.check_linux_listen_wg(_config())
        assert r.status is Status.WARN


class TestIpForward:
    def test_pass_when_runtime_and_persistent(self, tmp_path) -> None:
        drop_in = tmp_path / "99-outwarp.conf"
        drop_in.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed("1\n")), \
                patch("outwarp_server.diagnostics.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.glob.return_value = [drop_in]
            r = diagnostics.check_linux_ip_forward(_config())
        assert r.status is Status.PASS

    def test_warn_when_runtime_only(self, tmp_path) -> None:
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed("1\n")), \
                patch("outwarp_server.diagnostics.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.glob.return_value = []
            r = diagnostics.check_linux_ip_forward(_config())
        assert r.status is Status.WARN
        assert r.fix_kind == "auto"

    def test_fail_when_neither(self, tmp_path) -> None:
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed("0\n")), \
                patch("outwarp_server.diagnostics.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.glob.return_value = []
            r = diagnostics.check_linux_ip_forward(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "auto"


class TestNatMasquerade:
    def test_pass_when_rule_present(self) -> None:
        rule_out = (
            "-P POSTROUTING ACCEPT\n"
            "-A POSTROUTING -s 10.13.13.0/24 -j MASQUERADE\n"
        )
        with patch("outwarp_server.diagnostics._run_linux", return_value=_completed(rule_out)):
            r = diagnostics.check_linux_nat_masquerade(_config())
        assert r.status is Status.PASS

    def test_fail_when_rule_absent(self) -> None:
        with patch(
            "outwarp_server.diagnostics._run_linux",
            return_value=_completed("-P POSTROUTING ACCEPT\n"),
        ):
            r = diagnostics.check_linux_nat_masquerade(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "auto"


class TestFail2ban:
    def test_pass_when_present(self) -> None:
        with patch(
            "outwarp_server.diagnostics.shutil.which",
            return_value="/usr/bin/fail2ban-client",
        ):
            r = diagnostics.check_linux_fail2ban(_config())
        assert r.status is Status.PASS

    def test_warn_when_missing(self) -> None:
        with patch("outwarp_server.diagnostics.shutil.which", return_value=None):
            r = diagnostics.check_linux_fail2ban(_config())
        assert r.status is Status.WARN
        assert r.fix_kind == "interactive"


class TestReverseDns:
    def test_skip_for_ip_literal(self) -> None:
        r = diagnostics.check_linux_reverse_dns(_config(endpoint="203.0.113.42"))
        assert r.status is Status.SKIP

    def test_pass_when_rdns_matches(self) -> None:
        with patch("socket.gethostbyname", return_value="203.0.113.42"), \
                patch("socket.gethostbyaddr", return_value=("vpn.example.com", [], [])):
            r = diagnostics.check_linux_reverse_dns(_config(endpoint="vpn.example.com"))
        assert r.status is Status.PASS

    def test_warn_when_rdns_mismatches(self) -> None:
        with patch("socket.gethostbyname", return_value="203.0.113.42"), \
                patch("socket.gethostbyaddr", return_value=("other.example.com", [], [])):
            r = diagnostics.check_linux_reverse_dns(_config(endpoint="vpn.example.com"))
        assert r.status is Status.WARN

    def test_warn_when_no_ptr(self) -> None:
        with patch("socket.gethostbyname", return_value="203.0.113.42"), \
                patch("socket.gethostbyaddr", side_effect=socket.herror("no PTR")):
            r = diagnostics.check_linux_reverse_dns(_config(endpoint="vpn.example.com"))
        assert r.status is Status.WARN


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="Linux gather only")
def test_gather_includes_linux_checks() -> None:
    keys = {c.key for c in diagnostics.gather_checks()}
    assert "linux_binaries" in keys
    assert "linux_ip_forward" in keys
    assert "linux_nat_masquerade" in keys


class TestEnrollListener:
    """B-018: doctor was all green on a server where no enrolment could ever
    complete. The listener is now a check of its own, with the same three
    outcomes as the WG forwarder: loopback = pass, public = warn, absent = fail."""

    _HEADER = "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process\n"

    def _ss(self, local: str) -> str:
        return self._HEADER + f'LISTEN 0 128 {local} 0.0.0.0:* users:(("python3",pid=7,fd=4))\n'

    def test_pass_on_loopback(self) -> None:
        with patch("outwarp_server.diagnostics._run_linux",
                   return_value=_completed(self._ss("127.0.0.1:8444"))):
            r = diagnostics.check_linux_enroll_listener(_config())
        assert r.status is Status.PASS

    def test_warns_when_still_public(self) -> None:
        with patch("outwarp_server.diagnostics._run_linux",
                   return_value=_completed(self._ss("0.0.0.0:8444"))):
            r = diagnostics.check_linux_enroll_listener(_config())
        assert r.status is Status.WARN
        assert r.remediation_command == "outwarp-server restart"

    def test_fails_with_the_unit_to_start_under_systemd(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=True),
            patch("outwarp_server.diagnostics._run_linux",
                  return_value=_completed(self._HEADER)),
        ):
            r = diagnostics.check_linux_enroll_listener(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "auto"
        assert r.remediation_command == "systemctl start outwarp-enroll.service"

    def test_fails_pointing_at_the_serve_process_in_a_container(self) -> None:
        with (
            patch("outwarp_server.diagnostics._has_systemd", return_value=False),
            patch("outwarp_server.diagnostics._run_linux",
                  return_value=_completed(self._HEADER)),
        ):
            r = diagnostics.check_linux_enroll_listener(_config())
        assert r.status is Status.FAIL
        assert r.fix_kind == "manual"
        assert "serve" in r.remediation

