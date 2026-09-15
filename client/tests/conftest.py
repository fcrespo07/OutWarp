"""Shared fixtures for the OutWarp client test suite."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep every test away from the developer's real OutWarp installation.

    platformdirs resolves ``user_config_dir`` / ``user_log_dir`` from the
    environment at call time, so pointing the XDG_* (Linux) and APPDATA /
    LOCALAPPDATA (Windows) variables at ``tmp_path`` moves config.json,
    settings.json, known_servers.json and outwarp.log for the whole suite
    without patching every ``from outwarp.config import default_config_path``
    import site by hand. Before this, ``app.main()`` tests appended
    ``<MagicMock ...>`` lines to ``~/.local/state/OutWarp/log/outwarp.log``.

    The single-instance lock gets a per-test name for the same reason: with a
    real client connected on the machine, the default lock file was already
    held and ``app.main()`` bailed with "Another instance is already running".
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

    from outwarp import app as app_mod

    tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(
        app_mod._SingleInstanceLock.__init__,
        "__defaults__",
        (f"Local\\OutWarpClient-test-{tag}", f"outwarp-client-test-{tag}.lock"),
    )
    yield


@pytest.fixture(autouse=True)
def _no_real_killswitch_startup_cleanup():
    """Prevent `release_stale_async()` from ever running for real in a test.

    It fires a daemon thread that shells out to netsh (Windows) / the
    `outwarp-priv` helper via sudo (Linux) to clear a leftover kill switch
    from a crash — fire-and-forget by design, so callers (app.py, service.py,
    tui/app.py) never block startup on it. Left unmocked, that background
    thread outlives the test that spawned it and can fire its subprocess call
    while a *later* test has `subprocess.Popen`/`subprocess.run` patched for
    something unrelated — exactly what caused a flaky Windows CI failure in
    test_connect_falls_back_to_alternate_port, where a leaked thread's netsh
    call clobbered the wstunnel invocation the test was asserting about.

    Each caller does ``from outwarp.killswitch import release_stale_async``,
    which binds its own local name — patching only
    ``outwarp.killswitch.release_stale_async`` would not reach any of them,
    so every import site needs its own patch target.

    Autouse and session-wide: any test that drives app.main(), the daemon
    entry point, or a real Textual `run_test()` mount of the TUI app exercises
    this path, and it is easy to forget on a new one. Tests that specifically
    assert release_stale_async() was called (e.g. the on_mount regression
    test) still work — their own ``patch(...)`` nests fine on top of this.
    """
    with (
        patch("outwarp.app.release_stale_async"),
        patch("outwarp.service.release_stale_async"),
        patch("outwarp.tui.app.release_stale_async"),
    ):
        yield
