from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from outwarp_server.config import ServerConfig
from outwarp_server.i18n import cell_width, pad
from outwarp_server.i18n import t as tr


class NetworkCard(Container):
    DEFAULT_CSS = "NetworkCard { layout: vertical; height: auto; }"

    def __init__(self, config: ServerConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self):
        c = self._config
        yield Static(tr("tui.card.network"), classes="card-title")
        rows = [
            (tr("tui.net.endpoint"), f"{c.endpoint}:{c.port}"),
            (tr("tui.net.subnet"), c.subnet),
            (tr("tui.net.listen"), f"127.0.0.1:{c.wg_listen_port}"),
        ]
        w = max(cell_width(k) for k, _ in rows) + 2
        for k, v in rows:
            yield Static(f"{pad(k, w)}{v}", classes="value")
