"""Who owns the tunnel: one process at a time, whichever surface it is.

Before this module the only guard was the GUI's single-instance mutex. The
TUI, ``outwarp connect`` and the systemd daemon each built their own
TunnelManager against the same WireGuard interface and wstunnel port, and
the privileged helper's ``up`` runs ``wg-quick down`` first — so a second
owner tore the first one's interface down, the first one's watchdog saw the
tunnel die and reconnected, and the two flapped the link every few seconds.
That is exactly what "Run as background daemon" in the TUI did: ``enable
--now`` started the daemon next to the TUI's own tunnel.

The lock is the same cross-platform primitive the GUI used (a Windows named
mutex, ``flock`` on a file elsewhere), now shared by every entry point and
carrying the owner's pid so the loser can say who has it. Surfaces that lose
the lock become *viewers* (status from ``wg show`` via the helper, no
manager) instead of competing.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

MUTEX_NAME = "Global\\OutWarpClient"
LOCK_NAME = "outwarp-client.lock"
SERVICE_NAME = "outwarp-client.service"


class TunnelOwnerLock:
    """Cross-platform mutex: whoever holds it may bring the tunnel up.

    ``mutex_name`` / ``lock_file`` are exposed so tests use unique names
    instead of colliding with a real client on the developer's machine."""

    def __init__(self, mutex_name: str = MUTEX_NAME, lock_file: str = LOCK_NAME) -> None:
        self._handle: object | None = None
        self._lock_path: Path | None = None
        self._mutex_name = mutex_name
        self._lock_file = lock_file

    @property
    def path(self) -> Path:
        return Path(tempfile.gettempdir()) / self._lock_file

    def acquire(self) -> bool:
        if sys.platform == "win32":
            return self._acquire_windows()
        return self._acquire_posix()

    def release(self) -> None:
        if sys.platform == "win32":
            self._release_windows()
        else:
            self._release_posix()

    def _acquire_windows(self) -> bool:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, self._mutex_name)
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def _release_windows(self) -> None:
        if self._handle is not None:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(self._handle)
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    def _acquire_posix(self) -> bool:
        import fcntl
        self._lock_path = self.path
        try:
            self._handle = open(self._lock_path, "a+")  # noqa: SIM115
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self._handle:
                self._handle.close()
                self._handle = None
            return False
        # Owner pid for the loser's error message; best-effort.
        try:
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(str(os.getpid()))
            self._handle.flush()
        except OSError:
            pass
        return True

    def _release_posix(self) -> None:
        if self._handle is not None:
            import contextlib
            import fcntl
            with contextlib.suppress(OSError):
                fcntl.flock(self._handle, fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def owner_pid(lock_file: str = LOCK_NAME) -> int | None:
    """Pid written by the current holder, or None."""
    try:
        text = (Path(tempfile.gettempdir()) / lock_file).read_text().strip()
        pid = int(text)
    except (OSError, ValueError):
        return None
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
    return pid


def service_is_active() -> bool:
    """Is the systemd user unit currently running the tunnel? (Linux only.)"""
    if sys.platform != "linux" or shutil.which("systemctl") is None:
        return False
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def describe_owner() -> str:
    """Human-readable "who has the tunnel" for error messages and viewer modes."""
    if service_is_active():
        return f"the background service ({SERVICE_NAME})"
    pid = owner_pid()
    if pid:
        return f"another OutWarp process (pid {pid})"
    return "another OutWarp process"


OWNED_ELSEWHERE_HINT = (
    "Stop it first (`systemctl --user stop outwarp-client` for the service, or quit "
    "the other OutWarp window/TUI), or open this UI to watch it."
)
