"""Shared fixtures for the OutWarp client test suite."""

from __future__ import annotations

from unittest.mock import patch

import pytest


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
