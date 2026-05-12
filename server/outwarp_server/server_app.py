from __future__ import annotations

import logging
import sys
from pathlib import Path

from outwarp_server import __version__
from outwarp_server.config import ConfigError, ServerConfig, default_config_path
from outwarp_server.logs import setup_logging

log = logging.getLogger(__name__)

_MUTEX_NAME = "Global\\OutWarpServer"
_WINDOW_TITLE = "OutWarp Server"


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
        self._lock_path = Path(tempfile.gettempdir()) / "outwarp-server.lock"
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


def _resolve_ui_path() -> str:
    base = Path(sys._MEIPASS) / "ui" if hasattr(sys, "_MEIPASS") else Path(__file__).parent / "ui"
    return str(base / "index.html")


def main() -> int:
    _ensure_elevated()
    memory_handler = setup_logging()
    log.info("OutWarp Server GUI v%s starting", __version__)

    lock = _SingleInstanceLock()
    if not lock.acquire():
        log.error("Another instance is already running")
        return 1

    try:
        import webview

        from outwarp_server.api import Api
        from outwarp_server.server_manager import ServerManager
        from outwarp_server.server_tray import ServerTrayApp

        config = _try_load_config()
        manager: ServerManager | None = ServerManager(config) if config else None

        tray: ServerTrayApp

        def on_manager_replaced(new_mgr: ServerManager) -> None:
            nonlocal manager
            manager = new_mgr
            tray.update_manager(new_mgr)
            new_mgr.start()

        api = Api(memory_handler, manager, on_manager_replaced=on_manager_replaced)

        window = webview.create_window(
            title=_WINDOW_TITLE,
            url=_resolve_ui_path(),
            js_api=api,
            width=1200,
            height=780,
            min_size=(960, 640),
            background_color="#f6f5f1",
            resizable=True,
        )
        api.bind_window(window)

        def _show_window() -> None:
            try:
                window.show()
                window.restore()
            except Exception:
                log.exception("could not show window from tray")

        def _on_quit() -> None:
            log.info("Shutting down OutWarp Server")
            api.shutdown()
            tray.stop()
            try:
                window.destroy()
            except Exception:
                pass

        tray = ServerTrayApp(manager=manager, on_show=_show_window, on_quit=_on_quit)

        if manager is not None:
            manager.start()
            log.info("Server manager started: server=%s:%d", config.endpoint, config.port)

        tray.run()
        log.info("Tray running — opening webview window")
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)

        log.info("OutWarp Server shut down cleanly")
        return 0

    finally:
        lock.release()
