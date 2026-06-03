from __future__ import annotations

from textual.containers import Container
from textual.widgets import Sparkline, Static

from outwarp.tunnel_stats import TunnelStats


def _fmt_rate(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    if bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.2f} MB/s"
    return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "—"
    return f"{ms:.0f} ms"


def _fmt_age(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


class TrafficCard(Container):
    """Down/up rates, ping, last handshake — refreshed by DashboardScreen."""

    DEFAULT_CSS = """
    TrafficCard {
        layout: vertical;
        height: auto;
    }
    """

    def compose(self):
        yield Static("TRAFFIC", classes="card-title")
        yield Static("down  —", id="down", classes="value")
        yield Static("up    —", id="up", classes="value")
        yield Static("ping  —", id="ping", classes="value")
        yield Sparkline([0.0], summary_function=max, id="ping_spark")
        yield Static("last handshake  —", id="hs", classes="value")

    def update_stats(self, stats: TunnelStats, ping_history: list[float]) -> None:
        try:
            self.query_one("#down", Static).update(f"down  {_fmt_rate(stats.rx_rate_bps)}")
            self.query_one("#up", Static).update(f"up    {_fmt_rate(stats.tx_rate_bps)}")
            self.query_one("#ping", Static).update(f"ping  {_fmt_ms(stats.latency_ms)}")
            self.query_one("#hs", Static).update(
                f"last handshake  {_fmt_age(stats.last_handshake_age_s)}"
            )
            spark = self.query_one("#ping_spark", Sparkline)
            spark.data = ping_history or [0.0]
        except Exception:
            # Widgets removed mid-update (screen popped); benign.
            pass
