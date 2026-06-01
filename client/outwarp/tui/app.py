from __future__ import annotations

import logging
import threading

from textual.app import App

from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging
from outwarp.settings import load_settings
from outwarp.tunnel import TunnelManager, TunnelState
from outwarp.tui.screens.connecting import ConnectingScreen
from outwarp.tui.screens.dashboard import DashboardScreen
from outwarp.tui.screens.empty import EmptyScreen
from outwarp.tui.screens.failed import FailedScreen
from outwarp.tui.screens.logs import LogsScreen

log = logging.getLogger(__name__)


class OutWarpClientTUI(App):
    """Textual app entry point — `outwarp-cli tui` instantiates and runs this."""

    CSS_PATH = "styles.tcss"
    TITLE = "OutWarp · client"
    SCREENS = {
        "empty": EmptyScreen,
        "connecting": ConnectingScreen,
        "dashboard": DashboardScreen,
        "logs": LogsScreen,
        "failed": FailedScreen,
    }
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
        ("s", "settings", "Settings"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: ClientConfig | None = None
        self.manager: TunnelManager | None = None
        self._last_state: TunnelState | None = None
        # Surface non-recoverable construction errors (missing wstunnel, missing
        # platform) without crashing the whole TUI — the FailedScreen reads it.
        self._startup_error: str | None = None
        # Identifies the thread that owns the Textual event loop; captured in
        # on_mount and used by _on_state to distinguish the documented
        # same-thread RuntimeError case (call_from_thread refuses dispatch
        # within its own thread) from genuine shutdown errors.
        self._app_thread_id: int | None = None
        # Persisted preferences (shared with the pywebview GUI). Loaded once
        # at __init__ so the very first TunnelManager honours them; we re-read
        # in start_manager so a setting flipped via the modal also takes effect
        # on a reconnect cycle.
        self._settings = load_settings()

    def on_mount(self) -> None:
        setup_logging()
        self._app_thread_id = threading.get_ident()
        self.reload_config()

    def reload_config(self) -> None:
        """Load the .owcfg if present and route to the right initial screen.

        Called both at startup and after the user finishes the ImportModal —
        so importing transitions EmptyScreen → ConnectingScreen seamlessly.
        Honours ``settings.auto_connect``: when off, the manager is constructed
        but left disconnected and the dashboard handles the manual connect.
        """
        try:
            self.config = ClientConfig.load(default_config_path())
        except ConfigError:
            self.config = None
            self._push_unique("empty")
            return
        self.start_manager(auto=True)

    def start_manager(self, *, auto: bool = False) -> None:
        """Construct (or rebuild) the TunnelManager and, by default, start it.

        ``auto=True`` marks the call as an "initial load" — triggered by
        ``on_mount`` / ``reload_config`` rather than a user-driven retry. In
        that case ``settings.auto_connect=False`` causes us to wire the manager
        but skip ``manager.start()``, landing on the dashboard with a
        disconnected status until the user presses 'r' (reconnect). User-
        triggered callers (FailedScreen.retry, DashboardScreen.reconnect) leave
        ``auto`` at the default so the start always happens.
        """
        if self.config is None:
            return
        if self.manager is not None:
            try:
                self.manager.stop()
            except Exception:
                log.exception("Could not stop previous manager")
            self.manager = None
        # Re-read settings.json so a toggle the user flipped in the modal since
        # the last connect attempt (or in the pywebview GUI between TUI runs)
        # is honoured. Falls back to the in-memory copy on read failure.
        try:
            self._settings = load_settings()
        except Exception:
            log.exception("Could not reload settings.json")
        try:
            self.manager = TunnelManager(
                self.config,
                allow_tls_intercept=bool(self._settings.get("allow_tls_intercept", False)),
                auto_reconnect=bool(self._settings.get("auto_reconnect", True)),
            )
        except Exception as exc:
            log.exception("TunnelManager init failed")
            self._startup_error = str(exc)
            self._push_unique("failed")
            return
        self._startup_error = None
        self.manager.add_listener(self._on_state)
        self._last_state = None
        if auto and not bool(self._settings.get("auto_connect", True)):
            log.info("auto_connect disabled — staying disconnected; press 'r' to connect")
            self._push_unique("dashboard")
            return
        self._push_unique("connecting")
        self.manager.start()

    def _push_unique(self, screen_id: str) -> None:
        if self.screen_stack and getattr(self.screen, "name", None) == screen_id:
            return
        self.push_screen(screen_id)

    def _on_state(self, state: TunnelState) -> None:
        # TunnelManager fires this from its watchdog worker most of the time,
        # but the very first transition (DISCONNECTED→CONNECTING) happens
        # synchronously inside manager.start() — which we call from the app
        # thread itself. `call_from_thread` refuses same-thread dispatch with
        # RuntimeError, so for that specific case we route directly. Any other
        # RuntimeError (e.g. app already exited, message pump shut down during
        # action_quit) is NOT a same-thread issue — running _route_state from
        # the watchdog thread there would race the renderer, so we let it
        # propagate and let TunnelManager's listener-error swallow handle it.
        if self._app_thread_id is not None and threading.get_ident() == self._app_thread_id:
            self._route_state(state)
            return
        self.call_from_thread(self._route_state, state)

    def _route_state(self, state: TunnelState) -> None:
        if state == self._last_state:
            return
        self._last_state = state
        if state in (TunnelState.CONNECTING, TunnelState.RECONNECTING):
            self._push_unique("connecting")
        elif state == TunnelState.CONNECTED:
            self._push_unique("dashboard")
        elif state == TunnelState.FAILED:
            self._push_unique("failed")

    def action_help(self) -> None:
        from outwarp.tui.modals.help import HelpModal
        self.push_screen(HelpModal())

    def action_settings(self) -> None:
        from outwarp.tui.modals.settings import SettingsModal
        self.push_screen(SettingsModal())

    async def action_quit(self) -> None:
        if self.manager is not None:
            try:
                self.manager.stop()
            except Exception:
                log.exception("Error stopping manager on quit")
        self.exit(0)

    def on_unmount(self) -> None:
        if self.manager is not None:
            try:
                self.manager.stop()
            except Exception:
                log.exception("Error stopping manager on unmount")
