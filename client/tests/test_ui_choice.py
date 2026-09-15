"""Linux GUI/TUI choice: resolution, preference persistence, launcher plumbing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from outwarp import ui_choice
from outwarp.settings import load_settings


class TestResolveUi:
    @pytest.mark.parametrize(
        ("pref", "available", "desktop", "expected"),
        [
            ("auto", True, True, "gui"),
            ("auto", True, False, "tui"),   # SSH / console: no display
            ("auto", False, True, "tui"),
            ("gui", True, False, "gui"),    # explicit wins over no-display
            ("gui", False, True, "tui"),    # can't honour it: fall back
            ("tui", True, True, "tui"),
        ],
    )
    def test_matrix(self, pref, available, desktop, expected) -> None:
        settings = {"preferred_ui": pref}
        assert ui_choice.resolve_ui(settings, available=available, desktop=desktop) == expected

    def test_unknown_value_is_auto(self) -> None:
        assert ui_choice.preferred_ui({"preferred_ui": "bogus"}) == "auto"


class TestPreference:
    def test_set_and_load_round_trip(self) -> None:
        ui_choice.set_preferred_ui("tui")
        assert load_settings()["preferred_ui"] == "tui"
        assert ui_choice.preferred_ui() == "tui"
        ui_choice.set_preferred_ui("auto")
        assert ui_choice.preferred_ui() == "auto"

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            ui_choice.set_preferred_ui("web")  # type: ignore[arg-type]

    def test_default_setting_present(self) -> None:
        assert load_settings()["preferred_ui"] == "auto"


class TestGuiAvailable:
    def test_missing_pywebview(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "webview", None)
        ok, why = ui_choice.gui_available()
        assert ok is False
        assert ui_choice.INSTALL_HINT in why


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal emulators")
class TestTerminalCommand:
    def test_prefers_dollar_terminal(self, tmp_path: Path, monkeypatch) -> None:
        kitty = tmp_path / "kitty"
        kitty.write_text("#!/bin/sh\n")
        kitty.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setenv("TERMINAL", "kitty")
        assert ui_choice.terminal_command(["outwarp", "tui"]) == [
            "kitty", "--", "outwarp", "tui",
        ]

    def test_falls_back_to_candidates(self, tmp_path: Path, monkeypatch) -> None:
        foot = tmp_path / "foot"
        foot.write_text("#!/bin/sh\n")
        foot.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.delenv("TERMINAL", raising=False)
        assert ui_choice.terminal_command(["outwarp", "tui"]) == [str(foot), "outwarp", "tui"]

    def test_none_when_nothing_found(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.delenv("TERMINAL", raising=False)
        assert ui_choice.terminal_command(["outwarp", "tui"]) is None


class TestInstallGui:
    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only path")
    def test_runs_package_manager_then_pip(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        class _Done:
            returncode = 0

        def fake_run(cmd, check=False):
            calls.append(list(cmd))
            return _Done()

        monkeypatch.setattr(ui_choice, "venv_writable", lambda: True)
        monkeypatch.setattr(ui_choice, "system_gui_install_command",
                            lambda: ["pacman", "-S", "--needed", "--noconfirm", "webkit2gtk-4.1"])
        monkeypatch.setattr(ui_choice, "gui_extra_requirements", lambda: ["pywebview>=5.0"])
        monkeypatch.setattr(ui_choice, "gui_available", lambda: (True, "ok"))
        out: list[str] = []
        rc = ui_choice.install_gui(run=fake_run, echo=out.append)
        assert rc == 0
        assert calls[0][0] == "pacman"
        assert calls[1][:4] == [sys.executable, "-m", "pip", "install"]
        assert "pywebview>=5.0" in calls[1]
        assert any("GUI ready" in line for line in out)

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only path")
    def test_refuses_read_only_venv(self, monkeypatch) -> None:
        monkeypatch.setattr(ui_choice, "venv_writable", lambda: False)
        out: list[str] = []
        assert ui_choice.install_gui(run=lambda *a, **k: None, echo=out.append) == 2
        assert ui_choice.INSTALL_HINT in out[0]


def test_gui_extra_requirements_reads_the_installed_metadata() -> None:
    reqs = ui_choice.gui_extra_requirements()
    assert any(r.startswith("pywebview") for r in reqs)
    assert all(";" not in r for r in reqs)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux CLI path")
def test_cli_ui_sets_and_reports(capsys, monkeypatch) -> None:
    from outwarp import cli

    monkeypatch.setattr(ui_choice, "gui_available", lambda: (False, "pywebview not installed"))
    assert cli.main(["ui", "tui"]) == 0
    out = capsys.readouterr().out
    assert "preferred_ui = tui" in out
    assert "opens: tui" in out
    assert ui_choice.INSTALL_HINT in out
    assert load_settings()["preferred_ui"] == "tui"


@pytest.mark.skipif(sys.platform == "win32", reason="Linux CLI path")
def test_cli_launch_opens_tui_in_a_terminal_without_tty(monkeypatch) -> None:
    from outwarp import cli

    monkeypatch.setattr(ui_choice, "resolve_ui", lambda *a, **k: "tui")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(ui_choice, "terminal_command", lambda argv: ["fake-term", "-e", *argv])
    seen: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: seen.append(cmd) or 0)
    assert cli.main(["launch"]) == 0
    assert seen and seen[0][:2] == ["fake-term", "-e"] and seen[0][-1] == "tui"


@pytest.mark.skipif(sys.platform == "win32", reason="Linux CLI path")
def test_cli_gui_install_requires_root(capsys, monkeypatch) -> None:
    from outwarp import cli

    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert cli.main(["gui", "--install"]) == 2
    assert ui_choice.INSTALL_HINT in capsys.readouterr().err
