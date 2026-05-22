from __future__ import annotations

import contextlib
import logging
import logging.handlers
import sys
import threading
from collections import deque
from pathlib import Path
from threading import Lock

from platformdirs import user_log_dir

_APP_NAME = "OutWarp"
_MAX_BYTES = 512 * 1024
_BACKUP_COUNT = 1
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def default_log_path() -> Path:
    return Path(user_log_dir(_APP_NAME)) / "outwarp.log"


class MemoryLogHandler(logging.Handler):
    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buf: deque[str] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        with self._lock:
            self._buf.append(msg)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


def setup_logging(
    level: int = logging.INFO,
    log_path: Path | None = None,
    memory_capacity: int = 2000,
) -> MemoryLogHandler:
    log_path = log_path or default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(_DEFAULT_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    memory_handler = MemoryLogHandler(capacity=memory_capacity)
    memory_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(memory_handler)
    # Mirror to the parent console when there is one. PyInstaller --windowed
    # builds (and double-click launches) have no stdout, so skip the stream
    # handler there to avoid noise / crashes — sys.stdout is None in that case.
    if sys.stdout is not None and sys.stdout.isatty():
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)

    return memory_handler


def install_crash_logging() -> None:
    """Route uncaught exceptions (main thread + worker threads) to the log.

    GUI builds are PyInstaller --windowed: ``sys.stderr`` is None, so the
    default hooks drop the traceback into the void and a crash looks like a
    silent exit. Logging it first guarantees a post-mortem in outwarp.log; we
    then chain to the previous hook so console (CLI) behaviour is unchanged.
    Idempotent and safe to call once per process after setup_logging().
    """
    log = logging.getLogger("outwarp.crash")
    prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        with contextlib.suppress(Exception):
            prev_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    prev_threadhook = threading.excepthook

    def _threadhook(args):  # type: ignore[no-untyped-def]
        if not issubclass(args.exc_type, SystemExit):
            name = args.thread.name if args.thread else "?"
            log.critical(
                "Uncaught exception in thread %s",
                name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        with contextlib.suppress(Exception):
            prev_threadhook(args)

    threading.excepthook = _threadhook
