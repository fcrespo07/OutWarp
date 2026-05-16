from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

from outwarp import __version__
from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging

log = logging.getLogger(__name__)

_LOCK_NAME = "outwarp-client.lock"
_WINDOW_TITLE = "OutWarp"
_DEFAULT_MUTEX_NAME = "Global\\OutWarpClient"


class _SingleInstanceLock:
    """Cross-platform mutex to prevent running two instances.

    `mutex_name` / `lock_file` are exposed so tests can use unique names
    instead of colliding with a running production instance."""

    def __init__(
        self,
        mutex_name: str = _DEFAULT_MUTEX_NAME,
        lock_file: str = _LOCK_NAME,
    ) -> None:
        self._handle: object | None = None
        self._lock_path: Path | None = None
        self._mutex_name = mutex_name
        self._lock_file = lock_file

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
        self._lock_path = Path(tempfile.gettempdir()) / self._lock_file
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
            if self._lock_path and self._lock_path.exists():
                try:
                    self._lock_path.unlink()
                except Exception:
                    pass


def _try_load_config() -> ClientConfig | None:
    path = default_config_path()
    if not path.exists():
        return None
    try:
        return ClientConfig.load(path)
    except ConfigError as exc:
        log.warning("Config file corrupt: %s — starting with import screen", exc)
        return None


def _ensure_elevated() -> None:
    """On Windows, re-launch with UAC elevation if not already running as admin."""
    if sys.platform != "win32":
        return
    import ctypes

    if ctypes.windll.shell32.IsUserAnAdmin():
        return

    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = None
    elif sys.argv[0].endswith(".exe"):
        executable = sys.argv[0]
        params = None
    else:
        executable = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)

    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    sys.exit(0 if ret > 32 else 1)


def _resolve_ui_path() -> str:
    """Absolute path to ui/index.html (works in dev and PyInstaller bundles)."""
    base = Path(sys._MEIPASS) / "ui" if hasattr(sys, "_MEIPASS") else Path(__file__).parent / "ui"
    return str(base / "index.html")


def main() -> int:
    _ensure_elevated()
    memory_handler = setup_logging()
    log.info("OutWarp client v%s starting", __version__)

    lock = _SingleInstanceLock()
    if not lock.acquire():
        log.error("Another instance is already running — exiting")
        return 1

    try:
        import webview

        from outwarp.api import Api
        from outwarp.tray import TrayApp
        from outwarp.tunnel import TunnelManager

        config = _try_load_config()
        manager: TunnelManager | None = TunnelManager(config) if config else None

        # tray is filled in below before the closures fire
        tray: TrayApp

        def on_manager_replaced(new_mgr: TunnelManager) -> None:
            nonlocal manager
            manager = new_mgr
            tray.update_manager(new_mgr)
            new_mgr.start()

        api = Api(memory_handler, manager, on_manager_replaced=on_manager_replaced)

        if config:
            log.info(
                "Config loaded: server=%s:%d tunnel=%s",
                config.server.endpoint,
                config.server.port,
                config.wireguard.tunnel_name,
            )

        # Honour the user's "minimize to tray" preference: start with the
        # window hidden so only the tray is visible. Override on first run
        # (no profile yet) — the tray icon alone is useless if the user has
        # nothing to import yet, they need to see the import screen.
        settings = api.get_settings()
        start_hidden = bool(settings.get("minimize_to_tray", True)) and config is not None
        if start_hidden:
            log.info("minimize_to_tray=on — starting with the window hidden")

        window = webview.create_window(
            title=_WINDOW_TITLE,
            url=_resolve_ui_path(),
            js_api=api,
            width=1080,
            height=720,
            min_size=(880, 600),
            background_color="#f6f5f1",
            resizable=True,
            hidden=start_hidden,
        )
        api.bind_window(window)

        def _show_window() -> None:
            try:
                window.show()
                window.restore()
            except Exception:
                log.exception("could not show window from tray")

        def _on_quit() -> None:
            log.info("Shutting down OutWarp client")
            api.shutdown()
            tray.stop()
            try:
                window.destroy()
            except Exception:
                pass

        tray = TrayApp(manager=manager, on_show=_show_window, on_quit=_on_quit)

        if manager is not None:
            manager.start()

        tray.run()
        log.info("Tray running — opening webview window")
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)

        log.info("OutWarp client shut down cleanly")
        return 0

    finally:
        lock.release()
