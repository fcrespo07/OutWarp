from __future__ import annotations

import contextlib

from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig


class StatusCard(Container):
    """Identity card: server endpoint, WG address and (optional) public IP."""

    DEFAULT_CSS = """
    StatusCard {
        layout: vertical;
        height: auto;
    }
    """

    def __init__(self, config: ClientConfig) -> None:
        super().__init__()
        self._config = config
        self._public_ip: str | None = None
        self._geo: str | None = None

    def compose(self):
        yield Static("EXIT", classes="card-title")
        yield Static(self._render_endpoint(), id="endpoint", classes="value")
        yield Static("LOCATION", classes="card-title")
        yield Static(self._geo or "—", id="geo", classes="value")
        yield Static("WG ADDRESS", classes="card-title")
        yield Static(self._config.wireguard.client_address, classes="value")

    def _render_endpoint(self) -> str:
        s = self._config.server
        return f"{s.endpoint}:{s.port}"

    def set_geo(self, label: str | None) -> None:
        self._geo = label
        with contextlib.suppress(Exception):
            self.query_one("#geo", Static).update(label or "—")
