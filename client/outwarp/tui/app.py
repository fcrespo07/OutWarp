from __future__ import annotations

import logging

from textual.app import App

from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging
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
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: ClientConfig | None = None
        self.manager: TunnelManager | None = None
        self._last_state: TunnelState | None = None
        # Surface non-recoverable construction errors (missing wstunnel, missing
        # platform) without crashing the whole TUI — the FailedScreen reads it.
        self._startup_error: str | None = None

    def on_mount(self) -> None:
        setup_logging()
        self.reload_config()

    def reload_config(self) -> None:
        """Load the .owcfg if present and route to the right initial screen.

        Called both at startup and after the user finishes the ImportModal —
        so importing transitions EmptyScreen → ConnectingScreen seamlessly.
        """
        try:
            self.config = ClientConfig.load(default_config_path())
        except ConfigError:
            self.config = None
            self._push_unique("empty")
            return
        self.start_manager()

    def start_manager(self) -> None:
        if self.config is None:
            return
        if self.manager is not None:
            try:
                self.manager.stop()
            except Exception:
                log.exception("Could not stop previous manager")
            self.manager = None
        try:
            self.manager = TunnelManager(self.config)
        except Exception as exc:
            log.exception("TunnelManager init failed")
            self._startup_error = str(exc)
            self._push_unique("failed")
            return
        self._startup_error = None
        self.manager.add_listener(self._on_state)
        self._last_state = None
        self._push_unique("connecting")
        self.manager.start()

    def _push_unique(self, screen_id: str) -> None:
        if self.screen_stack and getattr(self.screen, "name", None) == screen_id:
            return
        self.push_screen(screen_id)

    def _on_state(self, state: TunnelState) -> None:
        # Listener may fire from a worker thread — schedule on the app loop.
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
