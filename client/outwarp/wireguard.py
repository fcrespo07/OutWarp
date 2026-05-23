from __future__ import annotations

import ipaddress
import logging
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from outwarp.config import ClientConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TunnelStats:
    rx_bytes: int            # bytes received from the peer (server)
    tx_bytes: int            # bytes sent to the peer
    latest_handshake: int | None  # unix timestamp; None if never


_DEFAULT_WIN_WG = Path(r"C:\Program Files\WireGuard\wg.exe")


def _find_wg_bin() -> Path | None:
    if sys.platform == "win32" and _DEFAULT_WIN_WG.exists():
        return _DEFAULT_WIN_WG
    found = shutil.which("wg")
    return Path(found) if found else None


def get_tunnel_stats(tunnel_name: str) -> TunnelStats | None:
    """Read transfer counters + last handshake from `wg show <name> dump`.

    Returns None if `wg` isn't available or the tunnel isn't up; callers
    treat that as "no data yet".
    """
    wg = _find_wg_bin()
    if wg is None:
        return None
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [str(wg), "show", tunnel_name, "dump"],
            capture_output=True, text=True, check=False, timeout=2,
            **extra,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    # The first dump line is the interface; peer lines come after. The client
    # only ever has one peer (the server), so we read the first peer line.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    parts = lines[1].split("\t")
    if len(parts) < 8:
        return None
    _pub, _preshared, _endpoint, _allowed, handshake, rx, tx, _keepalive = parts[:8]
    try:
        hs = int(handshake)
    except ValueError:
        hs = 0
    return TunnelStats(
        rx_bytes=int(rx) if rx.isdigit() else 0,
        tx_bytes=int(tx) if tx.isdigit() else 0,
        latest_handshake=hs if hs > 0 else None,
    )


def _resolve_bypass_networks(bypass_ips: list[str]) -> list[ipaddress.IPv4Network]:
    """Turn bypass entries into concrete IPv4 networks.

    Entries may be literal IPs, CIDRs, or **hostnames**. A hostname (e.g. a
    domain endpoint, possibly behind dynamic DNS) is resolved via DNS here, at
    connect time, so its current IP gets excluded from the tunnel. Without this
    the raw hostname reached `ipaddress.ip_network()` and blew up with
    "'host/32' does not appear to be an IPv4 or IPv6 network", failing every
    connect attempt. Unresolvable / IPv6-only entries are skipped with a warning
    — the tunnel still comes up, just without that exclusion.
    """
    nets: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()

    def _add(net: ipaddress.IPv4Network) -> None:
        if str(net) not in seen:
            seen.add(str(net))
            nets.append(net)

    for raw in bypass_ips:
        entry = raw.strip()
        if not entry:
            continue
        try:
            net = ipaddress.ip_network(entry if "/" in entry else f"{entry}/32", strict=False)
            if isinstance(net, ipaddress.IPv4Network):
                _add(net)
            continue
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(entry, None, family=socket.AF_INET)
        except OSError as exc:
            log.warning("Could not resolve bypass host %r (skipping exclusion): %s", entry, exc)
            continue
        for info in infos:
            _add(ipaddress.ip_network(f"{info[4][0]}/32"))
    return nets


def _allowed_ips_excluding(bypass_ips: list[str]) -> str:
    """Compute 0.0.0.0/0 minus bypass_ips as a comma-separated AllowedIPs string.

    Excluding bypass IPs from AllowedIPs is more reliable than adding host routes
    on top of a WireGuard tunnel, because the WireGuard-NT driver on Windows
    captures traffic before the OS routing table is consulted.
    """
    remaining: list[ipaddress.IPv4Network] = [ipaddress.ip_network("0.0.0.0/0")]
    for excl in _resolve_bypass_networks(bypass_ips):
        new_remaining: list[ipaddress.IPv4Network] = []
        for net in remaining:
            if excl.overlaps(net):
                new_remaining.extend(net.address_exclude(excl))
            else:
                new_remaining.append(net)
        remaining = new_remaining
    return ", ".join(str(n) for n in sorted(remaining))


def build_wg_conf(config: ClientConfig) -> str:
    wg = config.wireguard
    tunnel = config.tunnel
    # Always exclude the server endpoint itself from the tunnel. If it stayed
    # inside AllowedIPs, wstunnel's own connection to the server would be routed
    # back through the tunnel → loop, the WG handshake never completes. Resolved
    # at connect time (see _resolve_bypass_networks) so a domain endpoint works
    # too. Belt-and-suspenders on top of the server-provided bypass_ips.
    bypass = list(config.routing.bypass_ips)
    if config.server.endpoint:
        bypass.append(config.server.endpoint)
    allowed_ips = _allowed_ips_excluding(bypass) if bypass else "0.0.0.0/0"
    dns_line = f"DNS = {', '.join(wg.dns)}\n" if wg.dns else ""
    psk_line = f"PresharedKey = {wg.preshared_key}\n" if wg.preshared_key else ""
    return (
        "[Interface]\n"
        f"PrivateKey = {wg.client_private_key}\n"
        f"Address = {wg.client_address}\n"
        # Default 1380: 1500 (Ethernet) - 40 (IP/TCP) - 40 (TLS) - 8 (WS frame)
        # - 4 (wstunnel) - 28 (WG) = 1380. The wg-quick default of 1420 is sized
        # for WG-over-UDP; over TCP/TLS it causes silent drops of full-size return
        # packets (PMTUD black hole). User-overridable from the profile editor.
        f"MTU = {wg.mtu}\n"
        f"{dns_line}"
        "\n"
        "[Peer]\n"
        f"PublicKey = {wg.server_public_key}\n"
        f"{psk_line}"
        f"AllowedIPs = {allowed_ips}\n"
        f"Endpoint = 127.0.0.1:{tunnel.local_port}\n"
        "PersistentKeepalive = 25\n"
    )
