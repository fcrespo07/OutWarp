from __future__ import annotations

import contextlib

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
        yield Static(f"iface   {wg.tunnel_name}", id="tc-iface", classes="value")
        yield Static(f"peer    {_truncate(wg.server_public_key)}", id="tc-peer", classes="value")
        yield Static(f"remote  {tn.remote_host}:{tn.remote_port}", id="tc-remote", classes="value")
        yield Static(f"mtu     {wg.mtu}", id="tc-mtu", classes="value")
        yield Static(f"dns     {', '.join(wg.dns)}", id="tc-dns", classes="value")

    def update_config(self, config: ClientConfig) -> None:
        """Repaint the card's values from a (possibly edited) config.

        Called by DashboardScreen.on_screen_resume after the profile editor
        saves and start_manager() re-routes back to the dashboard — without
        this, the cached Static widgets keep the values from initial compose.
        """
        self._config = config
        wg = config.wireguard
        tn = config.tunnel
        # Card may not be mounted yet — in that case compose() will pick up
        # the fresh _config on first mount, so silently skipping is correct.
        with contextlib.suppress(Exception):
            self.query_one("#tc-iface", Static).update(f"iface   {wg.tunnel_name}")
            peer = _truncate(wg.server_public_key)
            self.query_one("#tc-peer", Static).update(f"peer    {peer}")
            remote = f"{tn.remote_host}:{tn.remote_port}"
            self.query_one("#tc-remote", Static).update(f"remote  {remote}")
            self.query_one("#tc-mtu", Static).update(f"mtu     {wg.mtu}")
            self.query_one("#tc-dns", Static).update(f"dns     {', '.join(wg.dns)}")
