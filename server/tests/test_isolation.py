"""Guard: the suite must never touch the developer's real OutWarp state."""

from __future__ import annotations

from pathlib import Path

from outwarp_server.logs import default_log_path


def test_log_path_lives_under_tmp(tmp_path: Path) -> None:
    p = default_log_path()
    assert tmp_path in p.parents, p
    # On Windows pytest's tmp dir itself lives under %LOCALAPPDATA%\Temp, so
    # "not under home" only proves something when tmp_path is outside home.
    if Path.home() not in tmp_path.parents:
        assert Path.home() not in p.parents, p
