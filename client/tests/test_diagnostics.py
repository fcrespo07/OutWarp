from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp.diagnostics import Status, check_sudoers

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only sudoers check")


def _fake_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "outwarp-priv"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    return helper


def test_sudoers_check_uses_sudo_list_not_execution(tmp_path: Path) -> None:
    """Regression: the helper has no `version` subcommand, so probing by
    running one reported every install as misconfigured. `sudo -l <cmd>`
    answers "allowed without password?" without executing anything."""
    helper = _fake_helper(tmp_path)
    with patch.dict("os.environ", {"OUTWARP_HELPER": str(helper)}), \
         patch("outwarp.diagnostics._run") as run:
        run.return_value = MagicMock(returncode=0, stdout=str(helper), stderr="")
        result = check_sudoers()

    assert result.status is Status.PASS
    assert run.call_args[0][0] == ["sudo", "-n", "-l", str(helper)]


def test_sudoers_check_fails_when_password_required(tmp_path: Path) -> None:
    helper = _fake_helper(tmp_path)
    with patch.dict("os.environ", {"OUTWARP_HELPER": str(helper)}), \
         patch("outwarp.diagnostics._run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="sudo: a password is required")
        result = check_sudoers()

    assert result.status is Status.FAIL
    assert "/etc/sudoers.d/outwarp" in (result.remediation or "")


def _fake_bin(dir_: Path, name: str, version: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text(f"#!/bin/sh\necho 'outwarp {version}'\n")
    p.chmod(0o755)
    return p


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shims")
def test_duplicate_binaries_warns_when_versions_differ(tmp_path: Path, monkeypatch) -> None:
    from outwarp import diagnostics

    _fake_bin(tmp_path / "a", "outwarp", "0.13.0")
    _fake_bin(tmp_path / "b", "outwarp-cli", "0.5.8")
    monkeypatch.setenv("PATH", f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")
    res = diagnostics.check_duplicate_binaries()
    assert res.status == diagnostics.Status.WARN
    assert "0.5.8" in res.detail and "0.13.0" in res.detail


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shims")
def test_duplicate_binaries_passes_for_a_single_install(tmp_path: Path, monkeypatch) -> None:
    from outwarp import diagnostics

    _fake_bin(tmp_path / "a", "outwarp", "0.13.0")
    # Same venv exposed twice (symlink) must count once.
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "outwarp-cli").symlink_to(tmp_path / "a" / "outwarp")
    monkeypatch.setenv("PATH", f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")
    res = diagnostics.check_duplicate_binaries()
    assert res.status == diagnostics.Status.PASS


def test_legacy_cli_name_reports_each_stale_reference(tmp_path: Path, monkeypatch) -> None:
    from outwarp import diagnostics, service

    launcher = tmp_path / "outwarp.desktop"
    launcher.write_text("[Desktop Entry]\nExec=outwarp-cli tui\n")
    comp = tmp_path / "outwarp-cli"
    comp.write_text("complete -F _x outwarp-cli\n")
    monkeypatch.setattr(diagnostics, "_SYSTEM_LAUNCHER", launcher)
    monkeypatch.setattr(diagnostics, "_LEGACY_NAME_FILES", (("bash completions", comp),))
    monkeypatch.setattr(service, "unit_uses_legacy_name", lambda unit_path=None: True)
    res = diagnostics.check_legacy_cli_name()
    assert res.status == diagnostics.Status.WARN
    assert "systemd user unit" in res.detail
    assert "launcher" in res.detail and "bash completions" in res.detail
    assert res.remediation_command == "outwarp service install"


def test_legacy_cli_name_passes_when_clean(tmp_path: Path, monkeypatch) -> None:
    from outwarp import diagnostics, service

    monkeypatch.setattr(diagnostics, "_SYSTEM_LAUNCHER", tmp_path / "missing.desktop")
    monkeypatch.setattr(diagnostics, "_LEGACY_NAME_FILES", ())
    monkeypatch.setattr(service, "unit_uses_legacy_name", lambda unit_path=None: False)
    assert diagnostics.check_legacy_cli_name().status == diagnostics.Status.PASS
