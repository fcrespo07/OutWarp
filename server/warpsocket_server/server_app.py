from __future__ import annotations

import logging
import secrets
import sys
from pathlib import Path

from warpsocket_server import __version__
from warpsocket_server.config import ConfigError, ServerConfig, default_config_path
from warpsocket_server.logs import setup_logging

log = logging.getLogger(__name__)

_MUTEX_NAME = "Global\\WarpSocketServer"
_PORT = 7172


class _SingleInstanceLock:
    def __init__(self) -> None:
        self._handle: object | None = None

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
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:
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
        import tempfile
        self._lock_path = Path(tempfile.gettempdir()) / "warpsocket-server.lock"
        try:
            self._handle = open(self._lock_path, "w")  # noqa: SIM115
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self._handle:
                self._handle.close()
                self._handle = None
            return False

    def _release_posix(self) -> None:
        if self._handle is not None:
            import fcntl
            try:
                fcntl.flock(self._handle, fcntl.LOCK_UN)
                self._handle.close()
            except Exception:
                pass
            self._handle = None


def _ensure_elevated() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    if getattr(sys, "frozen", False):
        exe = sys.executable
        extra = sys.argv[1:]
    else:
        exe = sys.argv[0] if sys.argv else sys.executable
        extra = sys.argv[1:]
    params = " ".join(f'"{a}"' for a in extra) if extra else None
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit(0 if ret > 32 else 1)


def _try_load_config() -> ServerConfig | None:
    path = default_config_path()
    if not path.exists():
        return None
    try:
        return ServerConfig.load(path)
    except ConfigError as exc:
        log.warning("Server config corrupt: %s — falling back to setup wizard", exc)
        return None


def main() -> int:
    _ensure_elevated()
    memory_handler = setup_logging()
    log.info("WarpSocket Server GUI v%s starting", __version__)

    lock = _SingleInstanceLock()
    if not lock.acquire():
        log.error("Another instance is already running")
        return 1

    try:
        from warpsocket_server.api import create_app
        from warpsocket_server.server_manager import ServerManager
        from warpsocket_server.server_tray import ServerTrayApp
        from warpsocket_server.webview import show_window, start

        config = _try_load_config()
        manager_ref: list[ServerManager | None] = [
            ServerManager(config) if config else None
        ]
        token = secrets.token_urlsafe(32)

        tray: ServerTrayApp

        def on_setup_complete(cfg: ServerConfig, mgr: ServerManager) -> None:
            manager_ref[0] = mgr
            tray.update_manager(mgr)
            mgr.start()
            log.info("Setup complete: server=%s:%d", cfg.endpoint, cfg.port)

        api_app = create_app(manager_ref, memory_handler, on_setup_complete, token)

        session = start(api_app, _PORT, token)

        def on_quit() -> None:
            log.info("Shutting down WarpSocket Server")
            m = manager_ref[0]
            if m is not None:
                m.stop()
            tray.stop()
            session.shutdown()

        tray = ServerTrayApp(
            manager=manager_ref[0],
            on_show=show_window,
            on_quit=on_quit,
        )

        if manager_ref[0] is not None:
            manager_ref[0].start()
            log.info("Server manager started: server=%s:%d", config.endpoint, config.port)

        tray.run()
        log.info(
            "Tray running — entering pywebview loop on http://127.0.0.1:%d", _PORT
        )
        session.run("WarpSocket Server")

        log.info("WarpSocket Server shut down cleanly")
        return 0

    finally:
        lock.release()
