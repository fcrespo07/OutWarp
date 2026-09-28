from __future__ import annotations

import logging
import sys
import threading

import pytest

from outwarp.logs import (
    MemoryLogHandler,
    default_log_path,
    install_crash_logging,
    setup_logging,
)


def test_default_log_path_is_absolute_under_app_dir():
    p = default_log_path()
    assert p.is_absolute()
    assert "OutWarp" in str(p)
    assert p.name == "outwarp.log"


def test_setup_logging_creates_log_file(tmp_path):
    log_path = tmp_path / "logs" / "wstunnel.log"
    setup_logging(log_path=log_path)
    logging.getLogger("test").info("hello")
    assert log_path.exists()
    assert "hello" in log_path.read_text(encoding="utf-8")


def test_setup_logging_returns_memory_handler(tmp_path):
    h = setup_logging(log_path=tmp_path / "log")
    assert isinstance(h, MemoryLogHandler)


def test_memory_handler_captures_records(tmp_path):
    h = setup_logging(log_path=tmp_path / "log")
    logging.getLogger("test").info("first")
    logging.getLogger("test").warning("second")
    snap = h.snapshot()
    assert any("first" in line for line in snap)
    assert any("second" in line for line in snap)


def test_memory_handler_capacity_limits_buffer(tmp_path):
    h = setup_logging(log_path=tmp_path / "log", memory_capacity=3)
    for i in range(10):
        logging.getLogger("test").info("msg-%d", i)
    snap = h.snapshot()
    assert len(snap) == 3
    assert "msg-9" in snap[-1]
    assert "msg-7" in snap[0]


def test_memory_handler_clear():
    h = MemoryLogHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    h.emit(logging.LogRecord("x", logging.INFO, "f", 0, "hello", None, None))
    assert h.snapshot() == ["hello"]
    h.clear()
    assert h.snapshot() == []


def test_setup_logging_replaces_existing_handlers(tmp_path):
    root = logging.getLogger()
    sentinel = logging.NullHandler()
    root.addHandler(sentinel)
    setup_logging(log_path=tmp_path / "log")
    assert sentinel not in root.handlers


def test_log_format_includes_level_and_logger_name(tmp_path):
    log_path = tmp_path / "log"
    setup_logging(log_path=log_path)
    logging.getLogger("outwarp.test").info("hello world")
    content = log_path.read_text(encoding="utf-8")
    assert "INFO" in content
    assert "outwarp.test" in content
    assert "hello world" in content


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


def test_since_keeps_counting_once_the_buffer_is_full() -> None:
    import logging as _logging

    from outwarp.logs import MemoryLogHandler

    h = MemoryLogHandler(capacity=3)
    h.setFormatter(_logging.Formatter("%(message)s"))
    lg = _logging.getLogger("client-since-test")
    lg.propagate = False
    lg.addHandler(h)
    lg.setLevel(_logging.INFO)
    seen = h.total
    for i in range(5):
        lg.info("line %d", i)
    lines, seen = h.since(seen)
    assert lines == ["line 2", "line 3", "line 4"]
    h.clear()
    lg.info("after clear")
    assert h.since(seen) == (["after clear"], 6)
