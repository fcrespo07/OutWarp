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

import functools
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

MUTEX_NAME = "Global\\OutWarpClient"
SHOW_EVENT_NAME = "Global\\OutWarpClientShow"
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
        kernel32 = _kernel32()
        handle = kernel32.CreateMutexW(None, True, self._mutex_name)
        # ctypes.get_last_error(), not a second GetLastError() call: the
        # interpreter can run Win32 calls of its own in between and reset the
        # value, and then a second instance thinks it created the mutex — two
        # GUIs, two tray icons, two TunnelManagers on one interface.
        last_error = ctypes.get_last_error()
        if not handle:
            log.warning("CreateMutexW(%s) failed (error %d)", self._mutex_name, last_error)
            return False
        if last_error == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def _release_windows(self) -> None:
        if self._handle is not None:
            kernel32 = _kernel32()
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
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


_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF


@functools.cache
def _kernel32():  # noqa: ANN202 — ctypes.WinDLL, Windows-only
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def request_show_existing(event_name: str = SHOW_EVENT_NAME) -> bool:
    """Ask the running GUI to bring its window to the front (Windows only).

    Without it a second launch — the Start-menu shortcut clicked while the
    first instance sits hidden in the tray — just exited, the user saw
    nothing and kept clicking. Returns True when the request was delivered.
    """
    if sys.platform != "win32":
        return False
    kernel32 = _kernel32()
    event_modify_state = 0x0002
    handle = kernel32.OpenEventW(event_modify_state, False, event_name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def listen_for_show_requests(
    on_show: Callable[[], None], event_name: str = SHOW_EVENT_NAME,
) -> bool:
    """Run `on_show` each time another launch calls request_show_existing().

    Windows only; the lock holder calls it once. The waiter is a daemon
    thread, so it dies with the process. Returns False when not started.
    """
    if sys.platform != "win32":
        return False
    kernel32 = _kernel32()
    handle = kernel32.CreateEventW(None, False, False, event_name)  # auto-reset
    if not handle:
        log.warning("CreateEventW(%s) failed (error %d)", event_name, _last_error())
        return False

    def _wait() -> None:
        while kernel32.WaitForSingleObject(handle, _INFINITE) == _WAIT_OBJECT_0:
            try:
                on_show()
            except Exception:
                log.exception("show request from a second launch failed")

    threading.Thread(target=_wait, daemon=True, name="show-requests").start()
    return True


def _last_error() -> int:
    import ctypes
    return ctypes.get_last_error()


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
