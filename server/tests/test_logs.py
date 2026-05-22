from __future__ import annotations

import logging
import sys
import threading

import pytest

from outwarp_server.logs import (
    MemoryLogHandler,
    default_log_path,
    install_crash_logging,
    setup_logging,
)


def test_default_log_path_is_absolute_under_app_dir():
    p = default_log_path()
    assert p.is_absolute()
    assert "OutWarp" in str(p)
    assert p.name == "outwarp-server.log"


def test_setup_logging_returns_memory_handler(tmp_path):
    h = setup_logging(log_path=tmp_path / "log")
    assert isinstance(h, MemoryLogHandler)


def test_memory_handler_captures_records(tmp_path):
    h = setup_logging(log_path=tmp_path / "log")
    logging.getLogger("test").info("first")
    snap = h.snapshot()
    assert any("first" in line for line in snap)


@pytest.fixture
def _restore_hooks():
    prev_excepthook = sys.excepthook
    prev_threadhook = threading.excepthook
    yield
    sys.excepthook = prev_excepthook
    threading.excepthook = prev_threadhook


def test_install_crash_logging_logs_main_thread_exception(tmp_path, _restore_hooks):
    h = setup_logging(log_path=tmp_path / "log")
    chained = []
    sys.excepthook = lambda *a: chained.append(a)
    install_crash_logging()
    try:
        raise RuntimeError("boom-main")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    snap = h.snapshot()
    assert any("Uncaught exception" in line and "boom-main" in line for line in snap)
    assert chained, "previous excepthook must still be chained"


def test_install_crash_logging_logs_thread_exception(tmp_path, _restore_hooks):
    h = setup_logging(log_path=tmp_path / "log")
    # Swap in a recorder as the previous hook so our chain target is this, not
    # pytest's (which would surface the deliberate crash as a test warning).
    chained = []
    threading.excepthook = lambda args: chained.append(args)
    install_crash_logging()

    def boom():
        raise RuntimeError("boom-thread")

    t = threading.Thread(target=boom, name="probe-thread")
    t.start()
    t.join()
    snap = h.snapshot()
    assert any("boom-thread" in line for line in snap)
    assert any("probe-thread" in line for line in snap)
    assert chained, "previous threading.excepthook must still be chained"


def test_install_crash_logging_passes_keyboardinterrupt_without_logging(tmp_path, _restore_hooks):
    h = setup_logging(log_path=tmp_path / "log")
    chained = []
    sys.excepthook = lambda *a: chained.append(a)
    install_crash_logging()
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())
    snap = h.snapshot()
    assert not any("Uncaught exception" in line for line in snap)
    assert chained, "KeyboardInterrupt must still chain to the previous hook"
