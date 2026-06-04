from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from outwarp_server.tui.tokens import DIM, OK, WARN


class ClientsSummary(Container):
    DEFAULT_CSS = "ClientsSummary { layout: vertical; height: auto; }"

    def compose(self):
        yield Static("CLIENTS", classes="card-title")
        yield Static("total    —", id="c-total", classes="value")
        yield Static("online   —", id="c-online", classes="value")
        yield Static("idle     —", id="c-idle", classes="value")
        yield Static("offline  —", id="c-offline", classes="value")

    def update_counts(self, total: int, online: int, idle: int, offline: int) -> None:
        try:
            self.query_one("#c-total", Static).update(f"total    {total}")
            self.query_one("#c-online", Static).update(
                f"online   [{OK}]{online}[/]"
            )
            self.query_one("#c-idle", Static).update(
                f"idle     [{WARN}]{idle}[/]"
            )
            self.query_one("#c-offline", Static).update(
                f"offline  [{DIM}]{offline}[/]"
            )
        except Exception:
            pass
