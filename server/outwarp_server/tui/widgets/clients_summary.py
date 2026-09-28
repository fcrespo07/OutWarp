from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from outwarp_server.i18n import pad
from outwarp_server.i18n import t as tr
from outwarp_server.tui.tokens import DIM, OK, WARN


def _row(key: str, value: str) -> str:
    return f"{pad(tr(key), 9)}{value}"


class ClientsSummary(Container):
    DEFAULT_CSS = "ClientsSummary { layout: vertical; height: auto; }"

    def compose(self):
        yield Static(tr("tui.card.clients"), classes="card-title")
        yield Static(_row("tui.st.total", "—"), id="c-total", classes="value")
        yield Static(_row("tui.st.online", "—"), id="c-online", classes="value")
        yield Static(_row("tui.st.idle", "—"), id="c-idle", classes="value")
        yield Static(_row("tui.st.offline", "—"), id="c-offline", classes="value")

    def update_counts(self, total: int, online: int, idle: int, offline: int) -> None:
        try:
            self.query_one("#c-total", Static).update(_row("tui.st.total", str(total)))
            self.query_one("#c-online", Static).update(
                _row("tui.st.online", f"[{OK}]{online}[/]")
            )
            self.query_one("#c-idle", Static).update(_row("tui.st.idle", f"[{WARN}]{idle}[/]"))
            self.query_one("#c-offline", Static).update(
                _row("tui.st.offline", f"[{DIM}]{offline}[/]")
            )
        except Exception:
            pass
