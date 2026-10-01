from __future__ import annotations

import contextlib

from rich.markup import escape
from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig
from outwarp.i18n import t as tr
from outwarp.tui.tokens import BAD, OK, WARN
from outwarp.tui.widgets.rows import kv, label_width
from outwarp.tunnel import TunnelState

# Maps the live tunnel state to (label, value-class). The value-class drives the
# colour via styles.tcss (.value.ok / .value.warn / .value.bad). Without this row
# the dashboard looked identical whether the tunnel was up or intentionally left
# disconnected (auto_connect=off) — the user had no way to tell.
_STATE_DISPLAY: dict[TunnelState, tuple[str, str]] = {
    TunnelState.CONNECTED: ("tui.state.connected", OK),
    TunnelState.CONNECTING: ("tui.state.connecting", WARN),
    TunnelState.RECONNECTING: ("tui.state.reconnecting", WARN),
    TunnelState.DISCONNECTED: ("tui.state.disconnected", WARN),
    TunnelState.FAILED: ("tui.state.failed", BAD),
}

_LABELS = (
    "tui.card.profile", "tui.card.state", "tui.card.route", "tui.card.exit",
    "tui.card.location", "tui.card.wg_address", "tui.card.kill_switch",
)


def route_label(route: dict | None) -> str:
    """The rung of the fallback ladder that carries the connection, in words
    (same wording as the GUI's `routeLabel`)."""
    if not route or not route.get("id"):
        return "—"
    rid = str(route["id"])
    if rid == "direct":
        return tr("tui.route.direct")
    if rid == "direct-hostile":
        return tr("tui.route.hostile")
    if rid == "direct-proxy":
        return tr("tui.route.proxy")
    if rid.startswith("port-") and rid[5:].isdigit():
        return tr("tui.route.port", port=route.get("port") or rid[5:])
    return str(route.get("label") or rid)


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
        self._kill_switch: bool | None = None

    def compose(self):
        yield Static(tr("tui.card.status"), classes="card-title")
        yield Static(self._row("tui.card.profile", escape(self._config.name or "—")), id="profile")
        yield Static(self._row("tui.card.state", "—"), id="state")
        yield Static(self._row("tui.card.route", "—"), id="route")
        yield Static(self._row("tui.card.exit", escape(self._render_endpoint())), id="endpoint")
        yield Static(self._row("tui.card.location", escape(self._geo or "—")), id="geo")
        yield Static(
            self._row("tui.card.wg_address", escape(self._config.wireguard.client_address)),
            id="wg-address",
        )
        yield Static(self._row("tui.card.kill_switch", self._kill_text()), id="kill-switch")

    def _row(self, key: str, value: str) -> str:
        return kv(tr(key), value, label_width([tr(k) for k in _LABELS]))

    def _kill_text(self) -> str:
        if self._kill_switch is None:
            return "—"
        return tr("tui.on") if self._kill_switch else tr("tui.off")

    def _render_endpoint(self) -> str:
        s = self._config.server
        return f"{s.endpoint}:{s.port}"

    def _show(self, widget_id: str, key: str, value: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(f"#{widget_id}", Static).update(self._row(key, value))

    def set_state(self, state: TunnelState | None) -> None:
        key, color = _STATE_DISPLAY.get(state, ("", ""))
        label = tr(key) if key else "—"
        self._show("state", "tui.card.state", f"[bold {color}]{label}[/]" if color else label)

    def set_managed_by_service(self, up: bool | None) -> None:
        """Viewer mode: the daemon owns the tunnel; report the interface."""
        label = tr("tui.service_up") if up else (
            tr("tui.service_down") if up is False else tr("tui.service")
        )
        color = OK if up else (BAD if up is False else "")
        self._show("state", "tui.card.state", f"[bold {color}]{label}[/]" if color else label)

    def set_route(self, route: dict | None) -> None:
        self._show("route", "tui.card.route", escape(route_label(route)))

    def set_kill_switch(self, enabled: bool | None) -> None:
        self._kill_switch = enabled
        self._show("kill-switch", "tui.card.kill_switch", self._kill_text())

    def set_geo(self, label: str | None) -> None:
        self._geo = label
        self._show("geo", "tui.card.location", escape(label or "—"))

    def update_config(self, config: ClientConfig) -> None:
        """Repaint endpoint + WG address after a profile edit, see
        TunnelCard.update_config for the rationale."""
        self._config = config
        self._show("profile", "tui.card.profile", escape(config.name or "—"))
        self._show("endpoint", "tui.card.exit", escape(self._render_endpoint()))
        self._show("wg-address", "tui.card.wg_address", escape(config.wireguard.client_address))
