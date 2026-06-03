from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from outwarp.config import ClientConfig


def _truncate(s: str, max_len: int = 24) -> str:
    if len(s) <= max_len:
        return s
    half = (max_len - 1) // 2
    return f"{s[:half]}…{s[-half:]}"


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
        wg = self._config.wireguard
        tn = self._config.tunnel
        yield Static("TUNNEL", classes="card-title")
        yield Static(f"iface   {wg.tunnel_name}", classes="value")
        yield Static(f"peer    {_truncate(wg.server_public_key)}", classes="value")
        yield Static(f"remote  {tn.remote_host}:{tn.remote_port}", classes="value")
        yield Static(f"mtu     {wg.mtu}", classes="value")
        yield Static(f"dns     {', '.join(wg.dns)}", classes="value")
