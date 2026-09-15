"""Guard: the suite must never touch the developer's real OutWarp state."""

from __future__ import annotations

from pathlib import Path

from outwarp.app import _SingleInstanceLock
from outwarp.config import default_config_path
from outwarp.logs import default_log_path


def test_config_and_log_paths_live_under_tmp(tmp_path: Path) -> None:
    for p in (default_config_path(), default_log_path()):
        assert tmp_path in p.parents, p
        assert Path.home() not in p.parents, p


def test_single_instance_lock_uses_a_per_test_name() -> None:
    lock = _SingleInstanceLock()
    assert "test-" in lock._lock_file
    assert "test-" in lock._mutex_name
    assert lock.acquire() is True
    lock.release()
