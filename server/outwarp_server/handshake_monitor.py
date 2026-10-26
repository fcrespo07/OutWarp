"""Per-peer WireGuard handshake logging.

wstunnel only knows a source IP and the shared path prefix, and WireGuard
drops a handshake it cannot authenticate without a trace, so "tunnel accepted,
no handshake" used to be invisible in the server logs (#36). This polls the
live peer table and logs the transitions that matter, by client name.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from outwarp_server.wireguard import LivePeer

log = logging.getLogger(__name__)

# WireGuard rekeys about every 2 minutes while traffic flows and the keepalive
# keeps an idle tunnel fresh; past this a peer's session is dead.
STALE_AFTER_S = 300


@dataclass
class _Seen:
    handshake: int | None
    fresh: bool


class HandshakeMonitor:
    def __init__(
        self,
        peers: Callable[[], dict[str, LivePeer]],
        clients: Callable[[], Iterable[tuple[str, str]]],
        now: Callable[[], float] = time.time,
    ) -> None:
        self._peers = peers
        self._clients = clients
        self._now = now
        self._seen: dict[str, _Seen] = {}

    def poll(self) -> None:
        """Log one line per client whose handshake state changed since the last poll."""
        live = self._peers()
        if not live:
            return  # interface down or `wg` unavailable: no data, not a verdict
        now = int(self._now())
        first = not self._seen
        for name, public_key in self._clients():
            peer = live.get(public_key)
            hs = peer.latest_handshake if peer else None
            fresh = hs is not None and now - hs <= STALE_AFTER_S
            prev = self._seen.get(public_key)
            self._seen[public_key] = _Seen(hs, fresh)
            if first:
                self._log_initial(name, peer, hs, now)
            elif fresh and (prev is None or not prev.fresh):
                log.info("peer %s: handshake completed", name)
            elif not fresh and prev is not None and prev.fresh:
                log.warning(
                    "peer %s: handshake lost (last one %ds ago); if its client keeps "
                    "opening tunnels, check that its keys and PSK still match",
                    name, now - hs if hs else -1,
                )

    @staticmethod
    def _log_initial(name: str, peer: LivePeer | None, hs: int | None, now: int) -> None:
        if peer is None:
            log.warning("peer %s: not present on the WireGuard interface", name)
        elif hs is None:
            log.info("peer %s: no handshake yet", name)
        else:
            log.info("peer %s: last handshake %ds ago", name, now - hs)
