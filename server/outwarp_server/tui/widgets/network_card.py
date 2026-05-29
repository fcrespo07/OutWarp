from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from outwarp_server.config import ServerConfig


class NetworkCard(Container):
    DEFAULT_CSS = "NetworkCard { layout: vertical; }"

    def __init__(self, config: ServerConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self):
        c = self._config
        yield Static("NETWORK", classes="card-title")
        yield Static(f"endpoint  {c.endpoint}:{c.port}", classes="value")
        yield Static(f"wg subnet {c.subnet}", classes="value")
        yield Static(f"wg listen 127.0.0.1:{c.wg_listen_port}", classes="value")
