from __future__ import annotations

import logging
from pathlib import Path

from textual.app import App
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from outwarp_server.config import ConfigError, ServerConfig
from outwarp_server.traffic_history import TrafficHistory
from outwarp_server.tui.screens.clients import ClientsScreen
from outwarp_server.tui.screens.dashboard import DashboardScreen
from outwarp_server.tui.screens.doctor import DoctorScreen
from outwarp_server.tui.screens.logs import LogsScreen

log = logging.getLogger(__name__)


class _NoConfigScreen(Screen):
    """Shown when server_config.json is missing — admin must run setup first."""

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self):
        yield Header()
        with Vertical(id="root"):
            yield Static("[bold]OutWarp server[/bold]")
            yield Static(self._message, classes="fail")
            yield Static(
                "Run [b]outwarp-server setup[/b] first, then re-launch the TUI."
            )
        yield Footer()


class OutWarpServerTUI(App):
    CSS_PATH = "styles.tcss"
    TITLE = "OutWarp · server"
    SCREENS = {
        "dashboard": DashboardScreen,
        "clients": ClientsScreen,
        "doctor": DoctorScreen,
        "logs": LogsScreen,
    }
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def __init__(self, config_dir: Path) -> None:
        super().__init__()
        self._config_dir = Path(config_dir)
        self.config_path: Path = self._config_dir / "server_config.json"
        self.config: ServerConfig | None = None
        self.history: TrafficHistory | None = None

    def on_mount(self) -> None:
        try:
            self.config = ServerConfig.load(self.config_path)
        except ConfigError as exc:
            self.push_screen(_NoConfigScreen(f"Cannot load config: {exc}"))
            return
        try:
            self.history = TrafficHistory(config=self.config)
        except Exception as exc:
            log.warning("TrafficHistory init failed: %s", exc)
            self.history = TrafficHistory.__new__(TrafficHistory)  # placeholder
        self.push_screen("dashboard")

    def reload_config(self) -> None:
        try:
            self.config = ServerConfig.load(self.config_path)
        except ConfigError:
            log.exception("Reload failed")

    def action_help(self) -> None:
        from outwarp_server.tui.modals.help import HelpModal
        self.push_screen(HelpModal())
