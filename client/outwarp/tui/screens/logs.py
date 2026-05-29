from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header

from outwarp.logs import default_log_path
from outwarp.tui.widgets.live_log import LiveLog


class LogsScreen(Screen):
    """Full-screen log tail with simple keyboard navigation."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", priority=True),
        Binding("g", "scroll_home", "Top"),
        Binding("G", "scroll_end", "Bottom", show=True, key_display="G"),
        Binding("q", "app.quit", "Quit", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="root"):
            yield LiveLog(default_log_path(), id="log")
        yield Footer()

    def action_scroll_home(self) -> None:
        try:
            self.query_one(LiveLog).scroll_home(animate=False)
        except Exception:
            pass

    def action_scroll_end(self) -> None:
        try:
            self.query_one(LiveLog).scroll_end(animate=False)
        except Exception:
            pass
