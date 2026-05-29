from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static


class ClientsSummary(Container):
    DEFAULT_CSS = "ClientsSummary { layout: vertical; }"

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
                f"online   [#2ee0b3]{online}[/]"
            )
            self.query_one("#c-idle", Static).update(
                f"idle     [#ff9b4a]{idle}[/]"
            )
            self.query_one("#c-offline", Static).update(
                f"offline  [#6e747e]{offline}[/]"
            )
        except Exception:
            pass
