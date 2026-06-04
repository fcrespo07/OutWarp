from __future__ import annotations

import contextlib

from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig
from outwarp.tunnel import TunnelState

# Maps the live tunnel state to (label, value-class). The value-class drives the
# colour via styles.tcss (.value.ok / .value.warn / .value.bad). Without this row
# the dashboard looked identical whether the tunnel was up or intentionally left
# disconnected (auto_connect=off) — the user had no way to tell.
_STATE_DISPLAY: dict[TunnelState, tuple[str, str]] = {
    TunnelState.CONNECTED: ("Connected", "ok"),
    TunnelState.CONNECTING: ("Connecting…", "warn"),
    TunnelState.RECONNECTING: ("Reconnecting…", "warn"),
    TunnelState.DISCONNECTED: ("Disconnected", "warn"),
    TunnelState.FAILED: ("Failed", "bad"),
}


class StatusCard(Container):
    """Identity card: tunnel state, server endpoint, WG address and public IP."""

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
        yield Static("STATUS", classes="card-title")
        yield Static("—", id="state", classes="value")
        yield Static("EXIT", classes="card-title")
        yield Static(self._render_endpoint(), id="endpoint", classes="value")
        yield Static("LOCATION", classes="card-title")
        yield Static(self._geo or "—", id="geo", classes="value")
        yield Static("WG ADDRESS", classes="card-title")
        yield Static(self._config.wireguard.client_address, id="wg-address", classes="value")

    def _render_endpoint(self) -> str:
        s = self._config.server
        return f"{s.endpoint}:{s.port}"

    def set_state(self, state: TunnelState | None) -> None:
        label, tone = _STATE_DISPLAY.get(state, ("—", ""))
        with contextlib.suppress(Exception):
            widget = self.query_one("#state", Static)
            widget.update(label)
            widget.set_classes(["value", tone] if tone else ["value"])

    def set_geo(self, label: str | None) -> None:
        self._geo = label
        with contextlib.suppress(Exception):
            self.query_one("#geo", Static).update(label or "—")

    def update_config(self, config: ClientConfig) -> None:
        """Repaint endpoint + WG address after a profile edit, see
        TunnelCard.update_config for the rationale."""
        self._config = config
        with contextlib.suppress(Exception):
            self.query_one("#endpoint", Static).update(self._render_endpoint())
            self.query_one("#wg-address", Static).update(config.wireguard.client_address)
