from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class FailedScreen(Screen):
    """Terminal state after max_attempts retries — offers a manual retry."""

    BINDINGS = [
        ("r", "retry", "Retry"),
        ("q", "quit", "Quit"),
        ("l", "open_logs", "Logs"),
    ]

    def action_open_logs(self) -> None:
        self.app.push_screen("logs")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static("[bold]Tunnel failed[/bold]")
            err = (
                getattr(self.app, "_startup_error", None)
                or (self.app.manager and self.app.manager.last_error)
                or "unknown error"
            )
            yield Static(f"[#ff5c7a]{err}[/]")
            yield Static("Press [b]r[/b] to retry, [b]l[/b] to view logs, [b]q[/b] to quit.")
        yield Footer()

    def action_retry(self) -> None:
        self.app.start_manager()
