from __future__ import annotations

import contextlib

from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig
from outwarp.i18n import t as tr
from outwarp.tunnel import TunnelState

# Maps the live tunnel state to (label, value-class). The value-class drives the
# colour via styles.tcss (.value.ok / .value.warn / .value.bad). Without this row
# the dashboard looked identical whether the tunnel was up or intentionally left
# disconnected (auto_connect=off) — the user had no way to tell.
_STATE_DISPLAY: dict[TunnelState, tuple[str, str]] = {
    TunnelState.CONNECTED: ("tui.state.connected", "ok"),
    TunnelState.CONNECTING: ("tui.state.connecting", "warn"),
    TunnelState.RECONNECTING: ("tui.state.reconnecting", "warn"),
    TunnelState.DISCONNECTED: ("tui.state.disconnected", "warn"),
    TunnelState.FAILED: ("tui.state.failed", "bad"),
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
        yield Static(tr("tui.card.status"), classes="card-title")
        yield Static("—", id="state", classes="value")
        yield Static(tr("tui.card.exit"), classes="card-title")
        yield Static(self._render_endpoint(), id="endpoint", classes="value")
        yield Static(tr("tui.card.location"), classes="card-title")
        yield Static(self._geo or "—", id="geo", classes="value")
        yield Static(tr("tui.card.wg_address"), classes="card-title")
        yield Static(self._config.wireguard.client_address, id="wg-address", classes="value")

    def _render_endpoint(self) -> str:
        s = self._config.server
        return f"{s.endpoint}:{s.port}"

    def set_state(self, state: TunnelState | None) -> None:
        key, tone = _STATE_DISPLAY.get(state, ("", ""))
        label = tr(key) if key else "—"
        with contextlib.suppress(Exception):
            widget = self.query_one("#state", Static)
            widget.update(label)
            widget.set_classes(["value", tone] if tone else ["value"])

    def set_managed_by_service(self, up: bool | None) -> None:
        """Viewer mode: the daemon owns the tunnel; report the interface."""
        label = tr("tui.service_up") if up else (
            tr("tui.service_down") if up is False else tr("tui.service")
        )
        tone = "ok" if up else ("bad" if up is False else "")
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
