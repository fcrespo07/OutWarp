from __future__ import annotations

import asyncio
import contextlib
import logging
import urllib.error
import urllib.request

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from outwarp.logs import default_log_path
from outwarp.tui.widgets.live_log import LiveLog
from outwarp.tui.widgets.status_card import StatusCard
from outwarp.tui.widgets.traffic_card import TrafficCard
from outwarp.tui.widgets.tunnel_card import TunnelCard
from outwarp.tunnel_stats import StatsSampler

log = logging.getLogger(__name__)


class DashboardScreen(Screen):
    """Two-column live status: cards on the left, tailing log on the right."""

    BINDINGS = [
        ("k", "disconnect", "Disconnect"),
        ("r", "reconnect", "Reconnect"),
        ("l", "open_logs", "Logs"),
        ("p", "open_profile", "Profile"),
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def action_open_logs(self) -> None:
        self.app.push_screen("logs")

    def action_open_profile(self) -> None:
        # Same destination as the SettingsModal's profile entry — both routes
        # end up at the per-profile editor (see screens/profile.py).
        self.app.push_screen("profile")

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield Header()
        with Horizontal(id="root"):
            with Vertical(classes="status-col"):
                yield Container(StatusCard(config))
                yield Container(TrafficCard())
                yield Container(TunnelCard(config))
            yield LiveLog(default_log_path())
        yield Footer()

    def on_mount(self) -> None:
        config = self.app.config
        self._sampler_iface: str | None = None
        self._sampler_peer: str | None = None
        self._rebuild_sampler(config)
        self.set_interval(1.0, self.refresh_stats)
        # Public IP / geo lookup runs once in the background — best-effort.
        asyncio.create_task(self._lookup_geo(), name="geo-lookup")

    def _rebuild_sampler(self, config) -> None:
        self._sampler = StatsSampler(
            iface=config.wireguard.tunnel_name,
            peer_endpoint_host=config.server.endpoint,
        )
        self._sampler_iface = config.wireguard.tunnel_name
        self._sampler_peer = config.server.endpoint

    def on_screen_resume(self) -> None:
        """Re-sync cards + stats sampler with the latest app.config.

        Textual memoises screens registered in ``App.SCREENS`` by class, so a
        DashboardScreen instance gets ``compose()``d once for the entire app
        lifetime. When the user edits the profile and we route back here, the
        cards still hold values from the first compose unless we push the new
        config in explicitly.
        """
        config = self.app.config
        if config is None:
            return
        for card_cls in (StatusCard, TunnelCard):
            with contextlib.suppress(Exception):
                self.query_one(card_cls).update_config(config)
        if (
            self._sampler_iface != config.wireguard.tunnel_name
            or self._sampler_peer != config.server.endpoint
        ):
            self._rebuild_sampler(config)

    def refresh_stats(self) -> None:
        try:
            stats = self._sampler.sample()
        except Exception:
            log.exception("StatsSampler failed")
            return
        try:
            card = self.query_one(TrafficCard)
            card.update_stats(stats, self._sampler.history_ping_ms())
        except Exception:
            pass

    async def _lookup_geo(self) -> None:
        # Per the goal sign-off: geolocate the exit IP via ip-api.com.
        # Strict timeout + best-effort — failures are silent and the card
        # falls back to showing the configured endpoint only.
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(None, self._fetch_geo)
        except Exception:
            return
        if not text:
            return
        with contextlib.suppress(Exception):
            self.query_one(StatusCard).set_geo(text)

    def _fetch_geo(self) -> str | None:
        url = "http://ip-api.com/line/?fields=status,country,city,query"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status != 200:
                    return None
                body = resp.read().decode("utf-8", errors="replace").strip()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        lines = body.splitlines()
        if not lines or lines[0].strip() != "success":
            return None
        country = lines[1].strip() if len(lines) > 1 else ""
        city = lines[2].strip() if len(lines) > 2 else ""
        ip = lines[3].strip() if len(lines) > 3 else ""
        label = ", ".join(part for part in (city, country) if part)
        return f"{label} ({ip})" if label else ip or None

    def action_disconnect(self) -> None:
        mgr = self.app.manager
        if mgr is not None:
            mgr.stop()
        self.app.exit(0)

    def action_reconnect(self) -> None:
        mgr = self.app.manager
        if mgr is None:
            return
        mgr.stop()
        self.app.start_manager()

    def action_help(self) -> None:
        from outwarp.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())
