from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server.platforms import ServerPlatform, get_server_platform
from outwarp_server.platforms.base import PlatformError
from outwarp_server.platforms.linux import LinuxServerPlatform


def test_get_server_platform_returns_subclass() -> None:
    p = get_server_platform()
    assert isinstance(p, ServerPlatform)


def test_server_platform_is_abstract() -> None:
    with pytest.raises(TypeError):
        ServerPlatform()  # type: ignore[abstract]


class TestLinuxPlatform:
    def test_wg_config_dir(self) -> None:
        assert LinuxServerPlatform().wg_config_dir() == Path("/etc/wireguard")

    @patch("outwarp_server.platforms.linux._SERVICE_PATH")
    @patch("outwarp_server.platforms.linux.os.chmod")
    @patch("outwarp_server.platforms.linux._run")
    def test_install_wstunnel_writes_unit_and_enables(
        self,
        mock_run: MagicMock,
        mock_chmod: MagicMock,
        mock_path: MagicMock,
    ) -> None:
        platform = LinuxServerPlatform()
        platform.install_wstunnel_service(
            "/usr/local/bin/wstunnel server --restrict-to 127.0.0.1:51820 "
            "--tls-certificate /etc/outwarp/cert.pem "
            "--tls-private-key /etc/outwarp/key.pem "
            "--restrict-http-upgrade-path-prefix secret wss://0.0.0.0:443"
        )
        mock_path.write_text.assert_called_once()
        unit_text = mock_path.write_text.call_args[0][0]
        assert "wss://0.0.0.0:443" in unit_text
        assert "127.0.0.1:51820" in unit_text
        # Path separator is platform-dependent in str(Path), so check for the exe name
        assert "wstunnel server" in unit_text
        assert "cert.pem" in unit_text

        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["systemctl", "daemon-reload"] in commands
        assert any("enable" in cmd for cmd in commands)

    @patch("outwarp_server.platforms.linux._ENROLL_SERVICE_PATH")
    @patch("outwarp_server.platforms.linux.os.chmod")
    @patch("outwarp_server.platforms.linux._run")
    def test_install_enroll_service_writes_unit_after_wstunnel_and_enables(
        self, mock_run: MagicMock, mock_chmod: MagicMock, mock_path: MagicMock,
    ) -> None:
        """B-018: a systemd install left nothing running the enrolment
        listener — it only lived inside ServerManager, which the wizard never
        keeps alive. Linux now gets a unit of its own, ordered after wstunnel
        since the listener is only reachable through its forward."""
        platform = LinuxServerPlatform()
        assert platform.manages_enroll_service is True
        platform.install_enroll_service(
            "/usr/local/bin/outwarp-server --config-dir /etc/outwarp enroll-listener"
        )
        unit_text = mock_path.write_text.call_args[0][0]
        assert (
            "ExecStart=/usr/local/bin/outwarp-server --config-dir /etc/outwarp enroll-listener"
            in unit_text
        )
        assert "After=network-online.target wstunnel-outwarp.service" in unit_text
        assert "Restart=always" in unit_text
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["systemctl", "daemon-reload"] in commands
        assert ["systemctl", "enable", "--now", "outwarp-enroll.service"] in commands

    @patch("outwarp_server.platforms.linux._run")
    def test_enroll_service_lifecycle(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="active\n")
        platform = LinuxServerPlatform()
        assert platform.is_enroll_running() is True
        platform.restart_enroll_service()
        with patch("outwarp_server.platforms.linux._ENROLL_SERVICE_PATH") as unit:
            unit.exists.return_value = True
            platform.uninstall_enroll_service()
            unit.unlink.assert_called_once()
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["systemctl", "is-active", "outwarp-enroll.service"] in commands
        assert ["systemctl", "restart", "outwarp-enroll.service"] in commands
        assert ["systemctl", "disable", "--now", "outwarp-enroll.service"] in commands

    @patch("outwarp_server.platforms.linux._run")
    def test_is_wstunnel_running_true(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="active\n")
        assert LinuxServerPlatform().is_wstunnel_running() is True

    @patch("outwarp_server.platforms.linux._run")
    def test_is_wstunnel_running_false(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="inactive\n")
        assert LinuxServerPlatform().is_wstunnel_running() is False

    @patch("outwarp_server.platforms.linux.Path")
    def test_is_wg_active(self, mock_path_cls: MagicMock) -> None:
        instance = MagicMock()
        mock_path_cls.return_value = instance

        instance.exists.return_value = True
        assert LinuxServerPlatform().is_wg_active() is True
        mock_path_cls.assert_called_with("/sys/class/net/wg0")

        instance.exists.return_value = False
        assert LinuxServerPlatform().is_wg_active() is False

    @patch("outwarp_server.platforms.linux._run")
    def test_install_wstunnel_raises_on_systemctl_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "systemctl", stderr="fail")
        with patch("outwarp_server.platforms.linux._SERVICE_PATH"), \
                patch("outwarp_server.platforms.linux.os.chmod"), \
                pytest.raises(PlatformError, match="Failed to enable"):
            LinuxServerPlatform().install_wstunnel_service("/usr/bin/wstunnel server")


    @patch("outwarp_server.platforms.linux._SYSCTL_DROP_IN")
    @patch("outwarp_server.platforms.linux._run")
    def test_uninstall_wg_config_disables_unit_and_removes_file(
        self, mock_run: MagicMock, mock_sysctl: MagicMock, tmp_path: Path
    ) -> None:
        conf = tmp_path / "wg0.conf"
        conf.write_text("[Interface]\n")
        mock_sysctl.exists.return_value = False
        with patch.object(LinuxServerPlatform, "wg_config_dir", return_value=tmp_path):
            LinuxServerPlatform().uninstall_wg_config()
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert any("disable" in c for c in cmds)
        assert not conf.exists()

    @patch("outwarp_server.platforms.linux._SYSCTL_DROP_IN")
    @patch("outwarp_server.platforms.linux._run")
    def test_uninstall_wg_config_removes_sysctl_drop_in(
        self, mock_run: MagicMock, mock_sysctl: MagicMock, tmp_path: Path
    ) -> None:
        mock_sysctl.exists.return_value = True
        with patch.object(LinuxServerPlatform, "wg_config_dir", return_value=tmp_path):
            LinuxServerPlatform().uninstall_wg_config()
        mock_sysctl.unlink.assert_called_once()
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert ["sysctl", "--system"] in cmds

    @pytest.mark.skipif(sys.platform == "win32", reason="Linux-only install paths (/opt/...)")
    def test_install_prefix_and_bin_link_match_installer(self) -> None:
        p = LinuxServerPlatform()
        _legacy = "/opt/outwarp-server"
        _exists = lambda self: str(self) == _legacy  # noqa: E731
        with patch.object(Path, "exists", autospec=True, side_effect=_exists):
            assert p.install_prefix() == Path(_legacy)
        assert p.bin_link() == Path("/usr/local/bin/outwarp-server")

    @patch("outwarp_server.platforms.linux._run")
    def test_restart_wstunnel_service(self, mock_run: MagicMock) -> None:
        LinuxServerPlatform().restart_wstunnel_service()
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert ["systemctl", "restart", "wstunnel-outwarp.service"] in cmds

    @patch("outwarp_server.platforms.linux._run")
    def test_restart_wstunnel_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "systemctl", stderr="fail")
        with pytest.raises(PlatformError, match="Failed to restart"):
            LinuxServerPlatform().restart_wstunnel_service()

    @patch("outwarp_server.platforms.linux._run")
    def test_uninstall_wstunnel_service(self, mock_run: MagicMock) -> None:
        with patch("outwarp_server.platforms.linux._SERVICE_PATH") as mock_path:
            mock_path.exists.return_value = True
            LinuxServerPlatform().uninstall_wstunnel_service()
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert any("disable" in c for c in cmds)

    @patch("outwarp_server.platforms.linux._run")
    def test_restart_wg(self, mock_run: MagicMock) -> None:
        LinuxServerPlatform().restart_wg()
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert ["systemctl", "restart", "wg-quick@wg0.service"] in cmds

    @patch("outwarp_server.platforms.linux._run")
    def test_restart_wg_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "systemctl", stderr="fail")
        with pytest.raises(PlatformError, match="Failed to restart"):
            LinuxServerPlatform().restart_wg()


class TestStubPlatforms:
    def test_windows_wstunnel_service_is_noop(self) -> None:
        from unittest.mock import patch

        from outwarp_server.platforms.windows import WindowsServerPlatform

        p = WindowsServerPlatform()
        # install/uninstall are no-ops on Windows (ServerManager owns wstunnel)
        p.install_wstunnel_service("/b server")
        p.uninstall_wstunnel_service()
        # Same for the enrolment listener: ServerManager hosts it in-process.
        assert p.manages_enroll_service is False
        p.install_enroll_service("/b enroll-listener")
        p.uninstall_enroll_service()
        p.restart_enroll_service()
        assert p.is_enroll_running() is False

        # is_wstunnel_running checks via tasklist; mock subprocess so it works off-platform
        with patch(
            "outwarp_server.platforms.windows._run",
            return_value=type("R", (), {"stdout": "", "returncode": 0})(),
        ):
            assert p.is_wstunnel_running() is False

    def test_is_wstunnel_running_true(self) -> None:
        """ServerManager.effective_state (get_status()'s reconciliation
        against the OS for a process that never started the service itself)
        relies on this returning True when wstunnel is actually up."""
        from unittest.mock import patch

        from outwarp_server.platforms.windows import WindowsServerPlatform

        p = WindowsServerPlatform()
        with patch(
            "outwarp_server.platforms.windows._run",
            return_value=type(
                "R", (), {"stdout": "wstunnel.exe   1234 Console  1   12,345 K", "returncode": 0},
            )(),
        ):
            assert p.is_wstunnel_running() is True

    def test_is_wg_active_true_and_false(self) -> None:
        from unittest.mock import patch

        from outwarp_server.platforms.windows import WindowsServerPlatform

        p = WindowsServerPlatform()
        with patch(
            "outwarp_server.platforms.windows._run",
            return_value=type("R", (), {"stdout": "STATE : 4 RUNNING", "returncode": 0})(),
        ):
            assert p.is_wg_active() is True
        with patch(
            "outwarp_server.platforms.windows._run",
            return_value=type("R", (), {"stdout": "", "returncode": 1060})(),
        ):
            assert p.is_wg_active() is False

    def test_wg_interface_name(self) -> None:
        from outwarp_server.platforms.windows import _WG_INTERFACE, WindowsServerPlatform
        assert WindowsServerPlatform().wg_interface_name() == _WG_INTERFACE


def _ps_result(stdout: str = "", stderr: str = "", returncode: int = 0):
    return type("R", (), {"stdout": stdout, "stderr": stderr, "returncode": returncode})()


class TestWindowsPrerequisites:
    """Bootstrap of the MSFT_NetNat WMI provider on Windows.

    The platform layer probes the provider and (if missing) tries to enable
    the Windows optional features that ship it. These tests cover the three
    outcomes: already present, enabled after auto-bootstrap (REBOOT_REQUIRED),
    and a damaged image where no feature enable can recover (FAILED).
    """

    def _platform(self):
        from outwarp_server.platforms.windows import WindowsServerPlatform
        return WindowsServerPlatform()

    def test_ok_when_class_already_registered(self) -> None:
        from outwarp_server.platforms.base import PrerequisiteStatus

        with patch(
            "outwarp_server.platforms.windows._ps",
            return_value=_ps_result(stdout="OK\n"),
        ) as mock_ps:
            result = self._platform().check_prerequisites()
        assert result.status is PrerequisiteStatus.OK
        # Probe ran exactly once — no feature enable attempted.
        assert mock_ps.call_count == 1

    def test_reboot_required_when_enable_returns_restart_needed(self) -> None:
        from outwarp_server.platforms.base import PrerequisiteStatus

        responses = iter([
            _ps_result(stdout="MISSING\n"),  # initial probe
            _ps_result(stdout="reboot\n"),   # Enable-WindowsOptionalFeature Containers
        ])
        with patch(
            "outwarp_server.platforms.windows._ps",
            side_effect=lambda *a, **kw: next(responses),
        ):
            result = self._platform().check_prerequisites()
        assert result.status is PrerequisiteStatus.REBOOT_REQUIRED
        assert "reboot" in result.remediation.lower()

    def test_ok_after_feature_enabled_in_place(self) -> None:
        from outwarp_server.platforms.base import PrerequisiteStatus

        responses = iter([
            _ps_result(stdout="MISSING\n"),  # initial probe
            _ps_result(stdout="enabled\n"),  # Containers enable
            _ps_result(stdout="OK\n"),       # re-probe after enable
        ])
        with patch(
            "outwarp_server.platforms.windows._ps",
            side_effect=lambda *a, **kw: next(responses),
        ):
            result = self._platform().check_prerequisites()
        assert result.status is PrerequisiteStatus.OK

    def test_failed_when_no_feature_brings_class_online(self) -> None:
        """PCFerran's case: features enable cleanly but the NAT WMI provider
        binaries are missing from the image, so the class never registers."""
        from outwarp_server.platforms.base import PrerequisiteStatus

        # Probe: MISSING. Then for each candidate feature: enable returns
        # 'enabled' but re-probe still says MISSING.
        responses = iter([
            _ps_result(stdout="MISSING\n"),  # initial probe
            _ps_result(stdout="enabled\n"),  # Containers enable
            _ps_result(stdout="MISSING\n"),  # re-probe after Containers
            _ps_result(stdout="enabled\n"),  # HypervisorPlatform enable
            _ps_result(stdout="MISSING\n"),  # re-probe after HypervisorPlatform
        ])
        with patch(
            "outwarp_server.platforms.windows._ps",
            side_effect=lambda *a, **kw: next(responses),
        ):
            result = self._platform().check_prerequisites()
        assert result.status is PrerequisiteStatus.FAILED
        # Remediation should mention concrete recovery paths the user can act on
        assert "DISM" in result.remediation
        assert "Linux" in result.remediation


class TestWindowsCreateNatRaises:
    """`_create_nat` used to swallow the failure as a log.warning, leaving
    the server in a zombie state (listening but unable to NAT). It now must
    raise PlatformError so callers can fail fast and surface the issue."""

    def _platform(self):
        from outwarp_server.platforms.windows import WindowsServerPlatform
        return WindowsServerPlatform()

    def test_translates_invalid_class_into_actionable_error(self) -> None:
        # Localised Spanish ("Clase no válida") and English ("Invalid class")
        # both come from Windows' WMI layer — translate either into the same
        # actionable PlatformError so the GUI shows a useful message.
        responses = iter([
            _ps_result(stdout=""),  # Get-NetNat probe: no existing rule
            _ps_result(stderr="New-NetNat : Clase no válida", returncode=1),
        ])
        with patch(
            "outwarp_server.platforms.windows._ps",
            side_effect=lambda *a, **kw: next(responses),
        ), pytest.raises(PlatformError, match="MSFT_NetNat WMI provider"):
            self._platform()._create_nat("10.0.0.0/24")

    def test_raises_with_underlying_error_on_other_failures(self) -> None:
        responses = iter([
            _ps_result(stdout=""),
            _ps_result(stderr="some other error", returncode=1),
        ])
        with patch(
            "outwarp_server.platforms.windows._ps",
            side_effect=lambda *a, **kw: next(responses),
        ), pytest.raises(PlatformError, match="some other error"):
            self._platform()._create_nat("10.0.0.0/24")

    def test_noop_when_nat_already_exists(self) -> None:
        with patch(
            "outwarp_server.platforms.windows._ps",
            return_value=_ps_result(stdout="OutWarp\n"),
        ) as mock_ps:
            # Should not raise, should not attempt New-NetNat (only one _ps call)
            self._platform()._create_nat("10.0.0.0/24")
        assert mock_ps.call_count == 1


class TestWindowsRestartWg:
    """FIX-07 regression: restart_wg() = uninstall_wg_config() (which always
    tears the NAT down via _remove_nat) + install_wg_config() (which never
    recreates it — only prepare_system() does, and restart_wg() never called
    that). Every restart left the server looking healthy — wstunnel up, WG
    handshakes completing — with silently no return traffic for clients."""

    def _platform(self, tmp_path: Path):
        from outwarp_server.platforms.windows import WindowsServerPlatform

        p = WindowsServerPlatform()
        conf_path = tmp_path / f"{p.wg_interface_name()}.conf"
        conf_path.write_text("[Interface]\n", encoding="utf-8")
        p.wg_config_dir = lambda: tmp_path  # type: ignore[method-assign]
        return p

    def test_recreates_nat_after_a_restart(self, tmp_path: Path) -> None:
        p = self._platform(tmp_path)
        calls: list[str] = []
        with (
            patch.object(p, "uninstall_wg_config", side_effect=lambda i: calls.append("down")),
            patch.object(p, "install_wg_config", side_effect=lambda t, i: calls.append("up")),
            patch.object(p, "_create_nat", side_effect=lambda s: calls.append(f"nat:{s}")),
        ):
            p.restart_wg(subnet="10.9.0.0/24")
        assert calls == ["down", "up", "nat:10.9.0.0/24"]

    def test_refuses_to_restart_without_a_subnet(self, tmp_path: Path) -> None:
        """No silent NAT loss on a caller that forgot to pass one — fail
        loudly and say exactly why, same as _create_nat's own failure mode."""
        p = self._platform(tmp_path)
        with (
            patch.object(p, "uninstall_wg_config"),
            patch.object(p, "install_wg_config"),
            patch.object(p, "_create_nat") as create_nat,
            pytest.raises(PlatformError, match="no subnet"),
        ):
            p.restart_wg()
        create_nat.assert_not_called()


class _FakePlatform(ServerPlatform):
    """Minimal concrete ServerPlatform recording call order, for testing
    the base class's reconcile() composition in isolation from any real OS
    interaction — see CONCEPTO-E in docs/history/OutWarp-fix-plan.md."""

    def __init__(self, *, active: bool = False) -> None:
        self.calls: list[tuple] = []
        self._active = active

    def install_wstunnel_service(self, exec_start: str) -> None: ...
    def uninstall_wstunnel_service(self) -> None: ...
    def is_wstunnel_running(self) -> bool: return False
    def restart_wstunnel_service(self) -> None: ...

    def install_wg_config(self, conf_text: str, interface: str = "wg0") -> None:
        self.calls.append(("install", conf_text, interface))

    def reload_wg(self, interface: str = "wg0") -> None: ...

    def is_wg_active(self, interface: str = "wg0") -> bool:
        return self._active

    def restart_wg(self, interface: str = "wg0", subnet: str | None = None) -> None:
        self.calls.append(("restart", interface, subnet))

    def uninstall_wg_config(self, interface: str = "wg0") -> None: ...
    def wg_config_dir(self) -> Path: return Path("/fake")

    def prepare_system(self, subnet: str, wss_port: int) -> None:
        self.calls.append(("prepare", subnet, wss_port))


class TestReconcile:
    """CONCEPTO-E: one idempotent entry point instead of callers sequencing
    prepare_system()/install_wg_config()/restart_wg() by hand — the exact
    footgun that caused FIX-07."""

    def test_always_prepares_system_first(self) -> None:
        p = _FakePlatform(active=False)
        p.reconcile("[Interface]\n", subnet="10.9.0.0/24", wss_port=443)
        assert p.calls[0] == ("prepare", "10.9.0.0/24", 443)
        assert p.calls[1] == ("install", "[Interface]\n", "wg0")

    def test_force_restart_on_active_interface_uses_restart_wg(self) -> None:
        p = _FakePlatform(active=True)
        p.reconcile(
            "[Interface]\n", subnet="10.9.0.0/24", wss_port=443, force_restart=True,
        )
        assert p.calls[0] == ("prepare", "10.9.0.0/24", 443)
        assert p.calls[1] == ("restart", "wg0", "10.9.0.0/24")

    def test_force_restart_on_inactive_interface_falls_back_to_install(self) -> None:
        # Nothing to tear down on a fresh interface — a full "restart" makes
        # no sense; reconcile() installs fresh instead.
        p = _FakePlatform(active=False)
        p.reconcile(
            "[Interface]\n", subnet="10.9.0.0/24", wss_port=443, force_restart=True,
        )
        assert p.calls[1] == ("install", "[Interface]\n", "wg0")

    def test_custom_interface_name_is_threaded_through(self) -> None:
        p = _FakePlatform(active=True)
        p.reconcile("conf", interface="OutWarp-Server", subnet="10.0.0.0/24", force_restart=True)
        assert p.calls[1] == ("restart", "OutWarp-Server", "10.0.0.0/24")
