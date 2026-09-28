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
    return Path(user_log_dir(_APP_NAME)) / "outwarp-server.log"


class MemoryLogHandler(logging.Handler):
    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buf: deque[str] = deque(maxlen=capacity)
        self._lock = Lock()
        self._total = 0

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        with self._lock:
            self._buf.append(msg)
            self._total += 1

    @property
    def total(self) -> int:
        """Lines ever emitted. len(snapshot()) stops growing once the buffer
        is full, so it cannot tell a watcher that something new arrived."""
        with self._lock:
            return self._total

    def since(self, seen: int) -> tuple[list[str], int]:
        """Lines emitted after the first `seen`, and the new running total.
        Lines that already fell off the end of the buffer are gone."""
        with self._lock:
            new = self._total - seen
            lines = list(self._buf)[-new:] if new > 0 else []
            return lines, self._total

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._buf)


def serve_log_path(config_dir: Path) -> Path:
    """Where `outwarp-server serve` also writes its log, inside the config
    directory. In Docker/Kubernetes the web panel runs as a separate process
    (a sidecar sharing /data) and cannot see serve's stdout; this file is how
    its Logs screen shows what the tunnel is doing."""
    return config_dir / "logs" / "serve.log"


def add_file_log(path: Path) -> None:
    """Also write the root logger to `path` (rotated like the main log)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    logging.getLogger().addHandler(handler)


class FileTail:
    """Follows a log file another process writes, across rotation.

    `backfill()` returns its last lines; `poll()` the complete lines written
    since the previous call. A rotated or truncated file (new inode, or
    shorter than what was read) is read again from the start.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._pos = 0
        self._ino: int | None = None
        self._partial = ""

    def backfill(self, limit: int = 400) -> list[str]:
        try:
            st = self.path.stat()
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return []
        self._ino, self._pos, self._partial = st.st_ino, st.st_size, ""
        return lines[-limit:]

    def poll(self) -> list[str]:
        try:
            st = self.path.stat()
        except OSError:
            return []
        if st.st_ino != self._ino or st.st_size < self._pos:
            self._ino, self._pos, self._partial = st.st_ino, 0, ""
        if st.st_size == self._pos:
            return []
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return []
        text = self._partial + chunk
        lines = text.split("\n")
        self._partial = lines.pop()
        return [ln for ln in lines if ln]


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

    return memory_handler


def install_crash_logging() -> None:
    """Route uncaught exceptions (main thread + worker threads) to the log.

    GUI builds are PyInstaller --windowed: ``sys.stderr`` is None, so the
    default hooks drop the traceback into the void and a crash looks like a
    silent exit. Logging it first guarantees a post-mortem in the log file; we
    then chain to the previous hook so console (CLI) behaviour is unchanged.
    Idempotent and safe to call once per process after setup_logging().
    """
    log = logging.getLogger("outwarp_server.crash")
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
