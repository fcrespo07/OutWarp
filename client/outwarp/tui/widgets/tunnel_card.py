from __future__ import annotations

import contextlib

from rich.markup import escape
from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig
from outwarp.i18n import t as tr
from outwarp.tui.widgets.rows import kv, label_width


def _truncate(s: str, max_len: int = 24) -> str:
    if len(s) <= max_len:
        return s
    half = (max_len - 1) // 2
    return f"{s[:half]}…{s[-half:]}"


_LABELS = (
    "tui.tunnel.iface", "tui.tunnel.peer", "tui.tunnel.remote", "tui.tunnel.mtu",
    "tui.tunnel.dns",
)


class TunnelCard(Container):
    """Static profile facts: iface, peer pubkey, remote endpoint, MTU, DNS."""

    DEFAULT_CSS = """
    TunnelCard {
        layout: vertical;
        height: auto;
    }
    """

    def __init__(self, config: ClientConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self):
        yield Static(tr("tui.card.tunnel"), classes="card-title")
        for widget_id, key, value in self._rows(self._config):
            yield Static(self._row(key, value), id=widget_id)

    @staticmethod
    def _rows(config: ClientConfig) -> list[tuple[str, str, str]]:
        wg, tn = config.wireguard, config.tunnel
        return [
            ("tc-iface", "tui.tunnel.iface", wg.tunnel_name),
            ("tc-peer", "tui.tunnel.peer", _truncate(wg.server_public_key)),
            ("tc-remote", "tui.tunnel.remote", f"{tn.remote_host}:{tn.remote_port}"),
            ("tc-mtu", "tui.tunnel.mtu", str(wg.mtu)),
            ("tc-dns", "tui.tunnel.dns", ", ".join(wg.dns)),
        ]

    @staticmethod
    def _row(key: str, value: str) -> str:
        labels = [tr(k) for k in _LABELS]
        return kv(tr(key), f"[bold]{escape(value)}[/]", label_width(labels))

    def update_config(self, config: ClientConfig) -> None:
        """Repaint after a profile edit: the dashboard screen is composed once
        and reused, so the cards would otherwise keep the first values."""
        self._config = config
        for widget_id, key, value in self._rows(config):
            with contextlib.suppress(Exception):
                self.query_one(f"#{widget_id}", Static).update(self._row(key, value))
