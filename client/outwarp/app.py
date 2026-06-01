from __future__ import annotations

import logging
import sys
import tempfile
import threading
import time
from pathlib import Path

from outwarp import __version__
from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import install_crash_logging, setup_logging

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


def _release_stale_kill_switch_async() -> None:
    """If a previous session crashed with the kill switch engaged, the netsh
    rules survive. Release unconditionally on every startup — it's a no-op
    when nothing is engaged, and prevents the user from being locked out of
    their network without realising why. Runs on a daemon thread so the two
    netsh subprocess calls (~300 ms total) don't gate the splash window."""
    def _work() -> None:
        try:
            from outwarp.platforms import get_platform

            get_platform().release_kill_switch()
        except Exception:
            log.exception("startup kill-switch cleanup failed (continuing)")
    threading.Thread(
        target=_work, daemon=True, name="outwarp-startup-killswitch",
    ).start()


def main() -> int:
    # As of 0.5.x the Textual TUI is the supported Linux UI: pywebview is
    # excluded from Linux wheels (see pyproject.toml's PEP 508 marker) so
    # the `import webview` below would ImportError before we got far enough
    # to render anything. Redirect to the TUI rather than crash — users who
    # genuinely want the tray GUI on Linux opt into it via
    # `pip install 'outwarp-client[gui-linux]'` and that import then resolves.
    if sys.platform == "linux":
        try:
            import webview  # noqa: F401 — presence test only
        except ImportError:
            from outwarp.cli import main as _cli_main
            return _cli_main(["tui"])

    _ensure_elevated()
    memory_handler = setup_logging()
    install_crash_logging()
    t0 = time.monotonic()

    def _stage(label: str) -> None:
        # Per-stage timing so we can spot future startup regressions. Format
        # matches the rest of the log line so it stays grep-friendly.
        log.info("startup [%5.2fs] %s", time.monotonic() - t0, label)

    _stage("OutWarp client v%s starting" % __version__)
    _release_stale_kill_switch_async()

    lock = _SingleInstanceLock()
    if not lock.acquire():
        log.error("Another instance is already running — exiting")
        return 1
    _stage("single-instance lock acquired")

    try:
        import webview
        _stage("imported pywebview")

        from outwarp.api import Api
        from outwarp.integrity import check_critical_files, format_report
        from outwarp.tray import TrayApp
        from outwarp.tunnel import TunnelManager
        _stage("imported outwarp modules")

        # Run early so a missing wstunnel.exe (typical Defender quarantine)
        # surfaces as a clear banner in the UI instead of as a generic
        # "could not start tunnel" error later. Cheap — a few stat() calls.
        integrity_issues = check_critical_files()
        for line in format_report(integrity_issues).splitlines():
            (log.warning if integrity_issues else log.info)("integrity: %s", line)
        _stage(f"integrity check ({len(integrity_issues)} issue(s))")

        config = _try_load_config()
        manager: TunnelManager | None = TunnelManager(config) if config else None
        _stage("config loaded + manager constructed (config=%s)" % (config is not None))

        # tray is filled in below before the closures fire
        tray: TrayApp

        def on_manager_replaced(new_mgr: TunnelManager) -> None:
            nonlocal manager
            manager = new_mgr
            tray.update_manager(new_mgr)
            new_mgr.start()

        api = Api(
            memory_handler,
            manager,
            on_manager_replaced=on_manager_replaced,
            integrity_issues=integrity_issues,
        )
        _stage("Api constructed")

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
            log.info(
                "minimize_to_tray=on — starting with the window hidden. "
                "Look for the OutWarp icon in the system tray (it may be in "
                "the hidden-icons flyout) and click it to open the window. "
                "Turn this off in Settings → System → Minimize to system tray."
            )

        window = webview.create_window(
            title=_WINDOW_TITLE,
            url=_resolve_ui_path(),
            js_api=api,
            width=1080,
            height=720,
            # Lowered so the responsive reflow (stats 2-col, stacked hero) is
            # reachable on small / high-DPI-scaled displays; the UI stays usable
            # down to this size (see ui/styles.css @media 860px).
            min_size=(760, 560),
            background_color="#f6f5f1",
            resizable=True,
            hidden=start_hidden,
            # Frameless: the native OS title bar clashes with the app's palette,
            # so we draw our own (see ui/app.jsx TitleBar). Drag + edge-resize
            # are re-implemented natively on Windows via api.window_* (and via
            # the pywebview-drag-region class elsewhere); easy_drag must be off
            # or the whole client area becomes a drag handle.
            frameless=True,
            easy_drag=False,
            shadow=True,
            # pywebview disables text selection by default; users need to be
            # able to copy log lines, fingerprints, error messages, etc.
            text_select=True,
        )
        _stage("webview window created")
        api.bind_window(window)
        _stage("api bound to window")

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

        # Let apply_update() quit the app after launching the installer so it
        # can replace our files and relaunch us.
        api.set_quit_handler(_on_quit)

        tray = TrayApp(
            manager=manager,
            on_show=_show_window,
            on_quit=_on_quit,
            api=api,
            lang_getter=lambda: api.get_settings().get("language", "es"),
        )
        _stage("tray constructed")

        # Auto-connect at launch unless the user opted out, or the profile has
        # expired (a dead profile would just thrash through the reconnect
        # schedule). Importing/editing a profile still connects via
        # on_manager_replaced regardless of this setting.
        if manager is not None:
            if not bool(settings.get("auto_connect", True)):
                log.info("auto_connect=off — not connecting at launch (use Connect)")
            elif manager.config.is_expired():
                log.warning(
                    "profile expired (%s) — not auto-connecting; import a fresh .owcfg",
                    manager.config.expires_at,
                )
            else:
                manager.start()
                _stage("tunnel manager started")

        tray.run()
        _stage("tray running — about to hand off to webview.start()")
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)

        log.info("OutWarp client shut down cleanly")
        return 0

    except Exception:
        # A fatal startup error in a --windowed build would otherwise vanish
        # (no console). Log it with the traceback so outwarp.log has a
        # post-mortem, then exit non-zero. (install_crash_logging covers
        # background threads; this covers the main setup path.)
        log.exception("Fatal error in client main()")
        return 1
    finally:
        lock.release()
