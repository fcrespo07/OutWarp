from __future__ import annotations

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
