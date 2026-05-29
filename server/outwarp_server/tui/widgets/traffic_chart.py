from __future__ import annotations

from textual.containers import Container
from textual.widgets import Sparkline, Static


class TrafficChart(Container):
    DEFAULT_CSS = "TrafficChart { layout: vertical; height: auto; }"

    def compose(self):
        yield Static("24H TRAFFIC", classes="card-title")
        yield Sparkline([0.0], summary_function=max, id="rx_spark")
        yield Static("rx", classes="info")
        yield Sparkline([0.0], summary_function=max, id="tx_spark")
        yield Static("tx", classes="info")
        yield Static("", id="totals", classes="value")

    def update_buckets(self, buckets: list[tuple[int, int, int]]) -> None:
        if not buckets:
            try:
                self.query_one("#totals", Static).update("[#6e747e]no data yet[/]")
            except Exception:
                pass
            return
        rx_series = [float(b[1]) for b in buckets]
        tx_series = [float(b[2]) for b in buckets]
        try:
            self.query_one("#rx_spark", Sparkline).data = rx_series
            self.query_one("#tx_spark", Sparkline).data = tx_series
            total_rx = sum(b[1] for b in buckets)
            total_tx = sum(b[2] for b in buckets)
            self.query_one("#totals", Static).update(
                f"24h  rx [#2ee0b3]{_fmt(total_rx)}[/]  tx [#2ee0b3]{_fmt(total_tx)}[/]"
            )
        except Exception:
            pass


def _fmt(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"
