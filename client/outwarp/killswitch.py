"""Single place that decides what to do with the OS-level kill switch for a
given tunnel state, and that clears it on process startup.

Before this module, the decision logic lived only inside outwarp.api.Api —
which is the pywebview GUI bridge. Since 0.5.x the TUI (and the systemd/SCM
`daemon` mode it autostarts) drives the tunnel through TunnelManager directly
and never touches Api at all, so the kill switch was silently inert on the
primary Linux path: it never engaged on a dropped connection, and a leftover
rule from a crash was never released either (CONCEPTO-E / FIX-06b in
docs/history/OutWarp-fix-plan.md). TunnelManager now calls reconcile() itself from every
state change when kill_switch_enabled is set, so all three surfaces share the
same behaviour instead of each having to remember to wire it up.
"""

from __future__ import annotations

import logging
import threading

from outwarp.config import ClientConfig
from outwarp.fallback import build_ladder
from outwarp.platforms import get_platform
from outwarp.routing import escape_set
from outwarp.tunnel import TunnelState
from outwarp.wireguard import _resolve_bypass_networks

log = logging.getLogger(__name__)


def reconcile(config: ClientConfig, state: TunnelState) -> None:
    """Engage/release the kill switch in response to a tunnel state change.

    Engagement happens when the tunnel is unexpectedly down — the
    RECONNECTING attempt window and the terminal FAILED state. Released on a
    successful CONNECTED or a clean DISCONNECTED (user pressed stop).
    CONNECTING (a fresh startup attempt) is left alone so a previously-
    engaged switch isn't released the moment a reconnect attempt starts.

    May raise outwarp.platforms.PlatformError from the underlying
    engage/release call — callers decide whether to swallow it (a state
    listener should never propagate and abort the whole dispatch loop) or
    let it surface to roll back a user-facing action.
    """
    if state in (TunnelState.RECONNECTING, TunnelState.FAILED):
        allowlist = resolved_allowlist(config)
        if not allowlist:
            log.error(
                "kill switch NOT engaged — no resolvable bypass addresses in "
                "profile (would lock the user out with no recovery path)"
            )
            return
        get_platform().engage_kill_switch(
            allowlist,
            tunnel_iface=config.wireguard.tunnel_name,
            tunnel_address=config.wireguard.client_address.split("/", 1)[0],
        )
        log.warning("kill switch engaged — outbound traffic blocked")
    elif state in (TunnelState.CONNECTED, TunnelState.DISCONNECTED):
        get_platform().release_kill_switch()


def resolved_allowlist(config: ClientConfig) -> list[str]:
    """escape_set() as concrete IPv4 addresses/CIDRs, ready for a firewall.

    The escape set may carry hostnames (a domain endpoint, a proxy); the same
    resolver build_wg_conf uses turns them into networks here, so the kill
    switch allowlist and the tunnel's AllowedIPs exclusion never disagree. A
    hostname handed raw to nft/netsh is rejected and the switch silently
    stays open — every domain-based profile hit that.
    """
    nets = _resolve_bypass_networks(escape_set(config, build_ladder(config)))
    return [str(n.network_address) if n.prefixlen == 32 else str(n) for n in nets]


def release_stale_async() -> None:
    """If a previous session crashed with the kill switch engaged, the OS
    rules survive it. Release unconditionally on every process startup — a
    no-op when nothing is engaged — so the user is never locked out of their
    network without realising why. Every entry point (GUI, TUI, daemon) must
    call this once at startup; runs on a daemon thread since the underlying
    netsh/iptables calls take a few hundred ms and startup shouldn't wait on
    them.
    """
    def _work() -> None:
        try:
            get_platform().release_kill_switch()
        except Exception:
            log.exception("startup kill-switch cleanup failed (continuing)")
    threading.Thread(
        target=_work, daemon=True, name="outwarp-startup-killswitch",
    ).start()
