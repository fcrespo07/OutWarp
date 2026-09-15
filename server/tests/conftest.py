"""Shared fixtures for the OutWarp server test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point platformdirs (server log, GUI settings) at ``tmp_path``.

    ``default_config_dir()`` already lives under ``/etc`` or ``ProgramData``
    and the tests pass explicit directories for it; ``user_log_dir`` did not
    have that protection, so a test driving ``setup_logging()`` with no path
    wrote into the developer's real ``~/.local/state`` tree.
    """
    home = tmp_path / "userdirs"
    for var, sub in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("APPDATA", "appdata"),
        ("LOCALAPPDATA", "localappdata"),
    ):
        d = home / sub
        d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(var, str(d))
    yield
