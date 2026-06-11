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
            port=443,
            cert_path=Path("/etc/outwarp/cert.pem"),
            key_path=Path("/etc/outwarp/key.pem"),
            upgrade_path="secret",
            wg_listen_port=51820,
            wstunnel_bin=Path("/usr/local/bin/wstunnel"),
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
            LinuxServerPlatform().install_wstunnel_service(
                port=443,
                cert_path=Path("/x"),
                key_path=Path("/y"),
                upgrade_path="s",
                wg_listen_port=51820,
                wstunnel_bin=Path("/usr/bin/wstunnel"),
            )


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
        p.install_wstunnel_service(443, Path("/c"), Path("/k"), "x", 51820, Path("/b"))
        p.uninstall_wstunnel_service()

        # is_wstunnel_running checks via tasklist; mock subprocess so it works off-platform
        with patch(
            "outwarp_server.platforms.windows._run",
            return_value=type("R", (), {"stdout": "", "returncode": 0})(),
        ):
            assert p.is_wstunnel_running() is False


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
