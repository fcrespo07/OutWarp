from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from pathlib import Path

from outwarp import __version__
from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.killswitch import release_stale_async
from outwarp.logs import install_crash_logging, setup_logging
from outwarp.ownership import (
    LOCK_NAME,
    MUTEX_NAME,
    TunnelOwnerLock,
    describe_owner,
    listen_for_show_requests,
    request_show_existing,
    service_is_active,
)
from outwarp.settings import load_settings

log = logging.getLogger(__name__)

_LOCK_NAME = LOCK_NAME
_WINDOW_TITLE = "OutWarp"
_DEFAULT_MUTEX_NAME = MUTEX_NAME


# Kept under its old name: tests and conftest patch `_SingleInstanceLock`;
# every surface (GUI, TUI, connect, daemon) now shares this one lock.
_SingleInstanceLock = TunnelOwnerLock

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
    # As of 0.5.x the Textual TUI is the supported Linux UI: pywebview is
    # excluded from Linux wheels (see pyproject.toml's PEP 508 marker) so
    # the `import webview` below would ImportError before we got far enough
    # to render anything. Redirect to the TUI rather than crash — users who
    # genuinely want the tray GUI on Linux opt into it via
    # `pip install 'outwarp-client[gui-linux]'` and that import then resolves.
    # Only the import is probed here (the deeper GTK/WebKit check lives in
    # outwarp.ui_choice.gui_available and runs in `outwarp gui` / `launch`
    # before reaching this point); tests stub `webview` to get past it.
    if sys.platform == "linux":
        try:
            import webview  # noqa: F401 — presence test only
        except ImportError:
            from outwarp.ui_choice import INSTALL_HINT

            print(f"OutWarp GUI not installed ({INSTALL_HINT}). Opening the TUI.",
                  file=sys.stderr)
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

    _stage(f"OutWarp client v{__version__} starting")
    startup_settings = load_settings()
    if bool(startup_settings.get("kill_switch", False)):
        # Same rule as the daemon: with the switch on, a rule left by a
        # crashed session is protection, not litter. reconcile() releases it
        # on CONNECTED / a clean stop.
        log.info("kill switch enabled — leaving any engaged rule in place at startup")
    else:
        release_stale_async()

    # The background service owns the tunnel while it runs: open as a viewer
    # (no TunnelManager.start(), status read from the interface) instead of
    # fighting it for the interface. Any other holder means a second GUI/TUI/
    # `connect` — exit and say who.
    service_managed = sys.platform == "linux" and service_is_active()
    lock = _SingleInstanceLock()
    if not service_managed and not lock.acquire():
        if request_show_existing():
            log.info("Another instance is already running — asked it to show its window")
        else:
            log.error("Another instance is already running (%s) — exiting", describe_owner())
        return 1
    _stage("service-managed viewer" if service_managed else "single-instance lock acquired")

    try:
        if sys.platform == "linux":
            # Before GTK initialises: otherwise Hyprland/GNOME see the window
            # as `python3` / the script name and no window rule can target it.
            from outwarp.desktop_linux import set_app_id
            set_app_id()
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
            service_managed=service_managed,
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

        quit_done = threading.Event()

        def _on_quit() -> None:
            if quit_done.is_set():
                return
            quit_done.set()
            log.info("Shutting down OutWarp client")
            api.shutdown()
            tray.stop()
            with contextlib.suppress(Exception):
                window.destroy()

        # Let apply_update() quit the app after launching the installer so it
        # can replace our files and relaunch us.
        api.set_quit_handler(_on_quit)
        # Hyprland (and most Wayland compositors) have no minimise: the title
        # bar button must hide to the tray instead, when there is one.
        api.tray_available = lambda: getattr(tray, "_icon", None) is not None

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
            if service_managed:
                log.info("tunnel managed by outwarp-client.service — GUI is a viewer")
            elif not bool(settings.get("auto_connect", True)):
                log.info("auto_connect=off — not connecting at launch (use Connect)")
            elif manager.config.is_expired():
                log.warning(
                    "profile expired (%s) — not auto-connecting; import a fresh .owcfg",
                    manager.config.expires_at,
                )
            else:
                manager.start()
                _stage("tunnel manager started")

        listen_for_show_requests(_show_window)
        tray.run()
        _stage("tray running — about to hand off to webview.start()")
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)

        # The window's own close button ends webview.start() without going
        # through the tray's Quit: without this the process exited leaving
        # WireGuard (0.0.0.0/0), wstunnel and an engaged kill switch behind,
        # with no UI left to undo them.
        _on_quit()
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
