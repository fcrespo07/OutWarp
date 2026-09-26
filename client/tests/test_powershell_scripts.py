"""Parse the repository's PowerShell scripts on the Windows CI runner.

They run on the maintainer's machine (release signing) or on user machines
(install-from-release.ps1), never in CI, so a syntax error would otherwise
only show up there. Parsing catches it without executing anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = sorted((Path(__file__).resolve().parents[2] / "scripts").glob("*.ps1"))


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda p: p.name)
def test_parses_without_errors(script: Path) -> None:
    command = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}', "
        "[ref]$null, [ref]$errors); "
        "$errors | ForEach-Object { $_.ToString() }; exit $errors.Count"
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_scripts_are_ascii() -> None:
    # Windows PowerShell 5.1 reads a BOM-less script as the ANSI code page, so
    # any non-ASCII character can turn into a syntax error on some machines.
    for script in _SCRIPTS:
        script.read_bytes().decode("ascii")
