from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from outwarp_server.tui.widgets.clients_summary import ClientsSummary
from outwarp_server.tui.widgets.network_card import NetworkCard
from outwarp_server.tui.widgets.services_card import ServicesCard
from outwarp_server.tui.widgets.tls_card import TlsCard
from outwarp_server.tui.widgets.traffic_chart import TrafficChart

log = logging.getLogger(__name__)

_ONLINE_WINDOW_SECONDS = 180


@dataclass
class _DashboardState:
    wstunnel: bool | None = None
    wg: bool | None = None
    online: int = 0
    idle: int = 0
    offline: int = 0


class DashboardScreen(Screen):
    """3-up cards on the left, traffic chart + top talkers on the right."""

    BINDINGS = [
        ("c", "open_clients", "Clients"),
        ("a", "add", "Add"),
        ("d", "open_doctor", "Doctor"),
        ("l", "open_logs", "Logs"),
        ("r", "restart", "Restart"),
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def action_open_clients(self) -> None:
        self.app.push_screen("clients")

    def action_open_doctor(self) -> None:
        self.app.push_screen("doctor")

    def action_open_logs(self) -> None:
        self.app.push_screen("logs")

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield Header()
        with Horizontal(id="root"):
            with Vertical(classes="col"):
                yield Container(ServicesCard())
                yield Container(NetworkCard(config))
                yield Container(TlsCard(config))
            with Vertical(classes="col"):
                yield Container(ClientsSummary())
                yield Container(TrafficChart())
                yield Container(Static("[bold]TOP TALKERS (1h)[/bold]\n[dim]—[/]",
                                       id="top"))
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self.refresh_dashboard)
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        try:
            self._refresh_services()
            self._refresh_clients()
            self._refresh_traffic()
        except Exception:
            log.exception("Dashboard refresh failed")

    def _refresh_services(self) -> None:
        from outwarp_server.platforms import PlatformError, get_server_platform
        platform = get_server_platform()
        try:
            wstunnel = platform.is_wstunnel_running()
        except PlatformError:
            wstunnel = None
        try:
            wg = platform.is_wg_active()
        except PlatformError:
            wg = None
        self.query_one(ServicesCard).update(wstunnel, wg)

    def _refresh_clients(self) -> None:
        from outwarp_server.wireguard import get_live_peers

        config = self.app.config
        live = get_live_peers()
        now = int(time.time())
        online = idle = offline = 0
        for c in config.clients:
            peer = live.get(c.public_key)
            if peer is None or peer.latest_handshake is None:
                idle += 1
                continue
            if (now - peer.latest_handshake) < _ONLINE_WINDOW_SECONDS:
                online += 1
            else:
                offline += 1
        total = len(config.clients)
        self.query_one(ClientsSummary).update_counts(total, online, idle, offline)

    def _refresh_traffic(self) -> None:
        history = self.app.history
        try:
            buckets = history.hourly_buckets(hours=24)
        except Exception:
            buckets = []
        self.query_one(TrafficChart).update_buckets(buckets)

        try:
            talkers = history.top_talkers(since_seconds=3600, limit=5)
        except Exception:
            talkers = []
        if talkers:
            lines = ["[bold]TOP TALKERS (1h)[/bold]"]
            for t in talkers:
                lines.append(
                    f"  {t['name']:<24} rx [#2ee0b3]{_fmt_bytes(t['rx_delta'])}[/]"
                    f"  tx [#2ee0b3]{_fmt_bytes(t['tx_delta'])}[/]"
                )
            self.query_one("#top", Static).update("\n".join(lines))
        else:
            self.query_one("#top", Static).update(
                "[bold]TOP TALKERS (1h)[/bold]\n[dim]no data yet[/]",
            )

    def action_add(self) -> None:
        from outwarp_server.tui.modals.add_client import AddClientModal
        self.app.push_screen(AddClientModal(), self._on_add_result)

    def _on_add_result(self, result) -> None:
        self.refresh_dashboard()

    def action_restart(self) -> None:
        from outwarp_server.tui.modals.confirm import ConfirmModal

        def _go(result: bool | None) -> None:
            if not result:
                return
            from outwarp_server import operations
            res = operations.restart_services(self.app.config)
            if res.errors:
                self.notify("Restart had issues: " + "; ".join(res.errors), severity="error")
            else:
                self.notify("Server restarted.", severity="information")

        self.app.push_screen(
            ConfirmModal(
                title="Restart services?",
                body="Regenerate wg0.conf and bounce wg-quick + wstunnel.",
                ok_label="Restart",
            ),
            _go,
        )

    def action_help(self) -> None:
        from outwarp_server.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"
