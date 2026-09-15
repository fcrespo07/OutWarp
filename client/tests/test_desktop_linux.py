"""Wayland/Hyprland integration helpers (verified live on Omarchy)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from outwarp import desktop_linux as dl


@pytest.fixture
def hypr(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "config" / "hypr"
    d.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return d


class TestHyprlandRule:
    def test_lua_config_gets_module_and_require(self, hypr: Path) -> None:
        main = hypr / "hyprland.lua"
        main.write_text('require("hypr.bindings")\n')
        assert dl.hyprland_config_kind() == "lua"
        assert dl.hyprland_rule_installed() is False
        msg = dl.install_hyprland_rule()
        assert "outwarp.lua" in msg
        assert (hypr / "outwarp.lua").read_text().startswith("-- OutWarp")
        assert 'o.window("^outwarp$"' in (hypr / "outwarp.lua").read_text()
        assert 'require("hypr.outwarp")' in main.read_text()
        assert dl.hyprland_rule_installed() is True
        dl.install_hyprland_rule()  # idempotent: one require line only
        assert main.read_text().count('require("hypr.outwarp")') == 1

    def test_hyprlang_config_gets_conf_and_source(self, hypr: Path) -> None:
        main = hypr / "hyprland.conf"
        main.write_text("monitor=,preferred,auto,1\n")
        assert dl.hyprland_config_kind() == "conf"
        dl.install_hyprland_rule()
        assert "windowrulev2 = float, class:^(outwarp)$" in (hypr / "outwarp.conf").read_text()
        assert "source = ~/.config/hypr/outwarp.conf" in main.read_text()
        assert dl.hyprland_rule_installed() is True

    def test_no_config_raises(self, hypr: Path) -> None:
        with pytest.raises(FileNotFoundError):
            dl.install_hyprland_rule()

    def test_snippet_defaults_to_lua(self, hypr: Path) -> None:
        assert "o.window" in dl.hyprland_rule_snippet()
        assert "windowrulev2" in dl.hyprland_rule_snippet("conf")


class TestTrayStatus:
    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")
    def test_wayland_without_backend_warns(self, monkeypatch) -> None:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
        monkeypatch.setattr(dl, "appindicator_available", lambda: (False, "no gi"))
        monkeypatch.setattr(dl, "status_notifier_watcher_present", lambda: True)
        state, detail = dl.tray_status()
        assert state == "warn" and "no gi" in detail

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")
    def test_backend_and_watcher_ok(self, monkeypatch) -> None:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
        monkeypatch.setattr(dl, "appindicator_available", lambda: (True, "AyatanaAppIndicator3"))
        monkeypatch.setattr(dl, "status_notifier_watcher_present", lambda: True)
        assert dl.tray_status()[0] == "ok"

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")
    def test_headless_skips(self, monkeypatch) -> None:
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.delenv("DISPLAY", raising=False)
        assert dl.tray_status()[0] == "skip"


def test_is_hyprland_from_env(monkeypatch) -> None:
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert dl.is_hyprland() is False
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    assert dl.is_hyprland() is True


def test_notify_passes_the_app_icon(monkeypatch) -> None:
    from outwarp import notify

    calls: list[list[str]] = []

    class _P:
        def __init__(self, cmd, **kw):
            calls.append(cmd)

    monkeypatch.setattr(notify.subprocess, "Popen", _P)
    monkeypatch.setattr(notify.sys, "platform", "linux")
    notify.notify("t", "b")
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls and "-i" in calls[0]
    assert calls[0][calls[0].index("-i") + 1].endswith("app_icon.png")


def test_enable_system_site_packages_rewrites_pyvenv_cfg(tmp_path: Path) -> None:
    from outwarp.ui_choice import enable_system_site_packages

    cfg = tmp_path / "pyvenv.cfg"
    cfg.write_text("home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.14.7\n")
    assert enable_system_site_packages(str(tmp_path)) is True
    assert "include-system-site-packages = true" in cfg.read_text()
    assert "false" not in cfg.read_text()
    cfg.write_text("home = /usr/bin\n")
    assert enable_system_site_packages(str(tmp_path)) is True
    assert cfg.read_text().rstrip().endswith("include-system-site-packages = true")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX")
def test_terminal_command_handles_xdg_terminal_exec(tmp_path: Path, monkeypatch) -> None:
    from outwarp import ui_choice

    x = tmp_path / "xdg-terminal-exec"
    x.write_text("#!/bin/sh\n")
    x.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("TERMINAL", "xdg-terminal-exec")
    assert ui_choice.terminal_command(["outwarp", "tui"]) == ["xdg-terminal-exec", "outwarp", "tui"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux autostart command")
def test_linux_autostart_command_uses_launch(monkeypatch) -> None:
    from outwarp import api

    monkeypatch.setattr(
        api.shutil, "which", lambda n: "/usr/local/bin/outwarp" if n == "outwarp" else None,
    )
    assert api._autostart_command() == ["/usr/local/bin/outwarp", "launch"]
