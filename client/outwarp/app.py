from __future__ import annotations

import logging
import secrets
import sys
import tempfile
from pathlib import Path

from outwarp import __version__
from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging

log = logging.getLogger(__name__)

_LOCK_NAME = "outwarp-client.lock"
_PORT = 7171


class _SingleInstanceLock:
    """Cross-platform mutex to prevent running two instances."""

    def __init__(self) -> None:
        self._handle: object | None = None
        self._lock_path: Path | None = None

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
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, "Global\\OutWarpClient")
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
        self._lock_path = Path(tempfile.gettempdir()) / _LOCK_NAME
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
        log.warning("Config file corrupt: %s — falling back to import screen", exc)
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


def main() -> int:
    _ensure_elevated()
    memory_handler = setup_logging()
    log.info("OutWarp client v%s starting", __version__)

    lock = _SingleInstanceLock()
    if not lock.acquire():
        log.error("Another instance is already running — exiting")
        return 1

    try:
        from outwarp.api import create_app
        from outwarp.tray import TrayApp
        from outwarp.tunnel import TunnelManager
        from outwarp.webview import show_window, start

        config = _try_load_config()
        manager_ref: list[TunnelManager | None] = [
            TunnelManager(config) if config else None
        ]
        token = secrets.token_urlsafe(32)

        tray: TrayApp

        def on_import(cfg: ClientConfig) -> None:
            existing = manager_ref[0]
            if existing is not None:
                existing.stop()
            new_manager = TunnelManager(cfg)
            manager_ref[0] = new_manager
            tray.update_manager(new_manager)
            new_manager.start()
            log.info(
                "Config imported: server=%s:%d tunnel=%s",
                cfg.server.endpoint,
                cfg.server.port,
                cfg.wireguard.tunnel_name,
            )

        api_app = create_app(manager_ref, memory_handler, on_import, token)

        if config:
            log.info(
                "Config loaded: server=%s:%d tunnel=%s",
                config.server.endpoint,
                config.server.port,
                config.wireguard.tunnel_name,
            )

        session = start(api_app, _PORT, token)

        def on_quit() -> None:
            log.info("Shutting down OutWarp")
            m = manager_ref[0]
            if m is not None:
                m.stop()
            tray.stop()
            session.shutdown()

        tray = TrayApp(
            manager=manager_ref[0],
            on_show=show_window,
            on_quit=on_quit,
        )

        if manager_ref[0] is not None:
            manager_ref[0].start()

        tray.run()
        log.info("Tray running — entering pywebview loop on http://127.0.0.1:%d", _PORT)
        session.run("OutWarp")

        log.info("OutWarp shut down cleanly")
        return 0

    finally:
        lock.release()
