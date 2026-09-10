"""Single source of truth for "what must stay outside the WireGuard tunnel".

This used to be computed four different, inconsistent ways: build_wg_conf,
the fallback ladder's own all_bypass_ips, and two separate spots in the kill
switch — the last two forgot the server endpoint and every alternate front the
ladder might dial, so the kill switch could engage with an allowlist that
blocked the client's own path back to the server (see CONCEPTO-B / FIX-03 in
OutWarp-fix-plan.md). escape_set() is the one function every consumer of this
set must call.
"""

from __future__ import annotations

from outwarp.config import ClientConfig
from outwarp.fallback import ConnectionStrategy


def escape_set(config: ClientConfig, ladder: list[ConnectionStrategy]) -> list[str]:
    """Union of every address that must stay outside the tunnel across all rungs.

    WireGuard is installed once with this union excluded from AllowedIPs, and
    it is also the kill switch's allowlist — the two must always agree: engaging
    the kill switch with anything less than what the tunnel itself excludes
    traps the client, unable to reconnect or even reach the server to fix it.
    """
    out: list[str] = list(config.routing.bypass_ips)
    if config.server.endpoint:
        out.append(config.server.endpoint)
    for r in ladder:
        if r.endpoint:
            out.append(r.endpoint)
        out.extend(r.bypass_ips)
    # De-dup preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for ip in out:
        if ip and ip not in seen:
            seen.add(ip)
            deduped.append(ip)
    return deduped
