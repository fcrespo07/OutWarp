"""B-034: a tunnel an unclean shutdown left installed is removed at boot/logon
and when the app starts, and nothing else WireGuard runs is touched."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from outwarp import cli
from outwarp.platforms.base import Platform
from outwarp.platforms.windows import WindowsPlatform


def _done(rc: int = 0, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr="")


@pytest.fixture
def platform(tmp_path, monkeypatch) -> WindowsPlatform:
    p = WindowsPlatform()
    monkeypatch.setattr(p, "_conf_dir", tmp_path)
    monkeypatch.setattr("outwarp.platforms.windows._WIREGUARD_EXE", tmp_path / "wireguard.exe")
    (tmp_path / "wireguard.exe").write_text("fake")
    return p


def _services(installed: set[str], calls: list[list[str]]):
    """Fake SCM: `installed` services exist until /uninstalltunnelservice."""
    def run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["sc", "query"]:
            name = cmd[2].split("$", 1)[1]
            return _done(0, "STATE : 4 RUNNING") if name in installed else _done(1060)
        if len(cmd) > 2 and cmd[1] == "/uninstalltunnelservice":
            installed.discard(cmd[2])
        return _done()
    return run


def test_removes_the_default_client_tunnel_left_by_an_older_version(platform) -> None:
    calls: list[list[str]] = []
    with patch("subprocess.run", side_effect=_services({"OutWarp"}, calls)):
        assert platform.remove_stale_tunnels() == ["OutWarp"]
    assert any(c[1:] == ["/uninstalltunnelservice", "OutWarp"] for c in calls if len(c) > 2)


def test_removes_marked_tunnels_and_leaves_everything_else(platform, tmp_path) -> None:
    (tmp_path / "Work.outwarp-client").touch()
    calls: list[list[str]] = []
    installed = {"Work", "OutWarp-Server", "home-vpn"}
    with patch("subprocess.run", side_effect=_services(installed, calls)):
        assert platform.remove_stale_tunnels() == ["Work"]
    # The server tunnel (same directory) and the user's own tunnel survive.
    assert installed == {"OutWarp-Server", "home-vpn"}
    assert not (tmp_path / "Work.outwarp-client").exists()


def test_nothing_installed_is_a_no_op_and_drops_orphan_markers(platform, tmp_path) -> None:
    (tmp_path / "Gone.outwarp-client").touch()
    calls: list[list[str]] = []
    with patch("subprocess.run", side_effect=_services(set(), calls)):
        assert platform.remove_stale_tunnels() == []
    assert not any("/uninstalltunnelservice" in c for c in calls)
    assert not (tmp_path / "Gone.outwarp-client").exists()


def test_install_marks_the_tunnel_and_uninstall_clears_the_mark(platform, tmp_path) -> None:
    calls: list[list[str]] = []
    installed: set[str] = set()

    def run(cmd, *args, **kwargs):
        if len(cmd) > 2 and cmd[1] == "/installtunnelservice":
            installed.add("Work")
        return _services(installed, calls)(cmd)

    with patch("subprocess.run", side_effect=run):
        platform.install_wg_tunnel("Work", "[Interface]")
        assert (tmp_path / "Work.outwarp-client").exists()
        platform.uninstall_wg_tunnel("Work")
    assert not (tmp_path / "Work.outwarp-client").exists()


@pytest.mark.parametrize("image", ["outwarp-gui.exe", "wstunnel.exe"])
def test_an_owner_process_counts_as_running(platform, image: str) -> None:
    def run(cmd, *args, **kwargs):
        hit = image in cmd[2]
        return _done(0, f'"{image}","4242","Console","1","10 K"' if hit else "INFO: none")
    with patch("subprocess.run", side_effect=run):
        assert platform.tunnel_owner_running() is True


def test_no_owner_process(platform) -> None:
    with patch("subprocess.run", return_value=_done(0, "INFO: No tasks are running")):
        assert platform.tunnel_owner_running() is False


def test_other_platforms_keep_no_tunnel_across_reboots() -> None:
    assert Platform.remove_stale_tunnels(MagicMock()) == []
    assert Platform.tunnel_owner_running(MagicMock()) is False


def test_recover_tunnel_leaves_a_running_owner_alone(capsys) -> None:
    fake = MagicMock()
    fake.tunnel_owner_running.return_value = True
    with patch("outwarp.platforms.get_platform", return_value=fake), \
            patch.object(cli, "setup_logging"):
        assert cli.main(["recover-tunnel"]) == 0
    fake.remove_stale_tunnels.assert_not_called()


def test_recover_tunnel_removes_stale_tunnels(capsys) -> None:
    fake = MagicMock()
    fake.tunnel_owner_running.return_value = False
    fake.remove_stale_tunnels.return_value = ["OutWarp"]
    with patch("outwarp.platforms.get_platform", return_value=fake), \
            patch.object(cli, "setup_logging"):
        assert cli.main(["recover-tunnel"]) == 0
    assert "OutWarp" in capsys.readouterr().out


def test_recover_tunnel_is_not_advertised() -> None:
    assert "recover-tunnel" not in cli.build_parser().format_help()
