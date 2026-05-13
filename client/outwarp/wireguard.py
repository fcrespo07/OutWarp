from __future__ import annotations

import ipaddress
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from outwarp.config import ClientConfig


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


def _allowed_ips_excluding(bypass_ips: list[str]) -> str:
    """Compute 0.0.0.0/0 minus bypass_ips as a comma-separated AllowedIPs string.

    Excluding bypass IPs from AllowedIPs is more reliable than adding host routes
    on top of a WireGuard tunnel, because the WireGuard-NT driver on Windows
    captures traffic before the OS routing table is consulted.
    """
    remaining: list[ipaddress.IPv4Network] = [ipaddress.ip_network("0.0.0.0/0")]
    for ip in bypass_ips:
        excl = ipaddress.ip_network(ip if "/" in ip else f"{ip}/32", strict=False)
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
    bypass = config.routing.bypass_ips
    allowed_ips = _allowed_ips_excluding(bypass) if bypass else "0.0.0.0/0"
    dns_line = f"DNS = {', '.join(wg.dns)}\n" if wg.dns else ""
    return (
        "[Interface]\n"
        f"PrivateKey = {wg.client_private_key}\n"
        f"Address = {wg.client_address}\n"
        f"{dns_line}"
        "\n"
        "[Peer]\n"
        f"PublicKey = {wg.server_public_key}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"Endpoint = 127.0.0.1:{tunnel.local_port}\n"
        "PersistentKeepalive = 25\n"
    )
