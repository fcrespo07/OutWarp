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


_RESOLVED_SYMLINK_PREFIXES = (
    # Default Debian/Ubuntu/Arch layout: stub-resolv.conf written by
    # systemd-resolved itself.
    "/run/systemd/resolve/",
    # Fedora / RHEL 9 layout: the distro ships a static resolv.conf shim under
    # /usr/lib/systemd that's just the 127.0.0.53 stub on a system where
    # systemd-resolved is the active resolver. Same "resolvconf -a fails with
    # signature mismatch" outcome as the canonical case.
    "/usr/lib/systemd/",
)


def _systemd_resolved_active() -> bool:
    """True on Linux when systemd-resolved owns ``/etc/resolv.conf``.

    In that setup openresolv's ``resolvconf -a`` refuses with
    ``signature mismatch`` (it only writes files it owns) and ``wg-quick up``
    aborts before the link comes up — observed on Arch + systemd-resolved.

    When this returns True, ``build_wg_conf`` emits ``PostUp``/``PreDown``
    hooks that drive systemd-resolved directly via ``resolvectl`` instead of
    the standard ``DNS = `` line that triggers the broken resolvconf path.

    Detection covers three layouts:

    1. ``/etc/resolv.conf`` is a symlink under ``/run/systemd/resolve/``
       (Debian/Ubuntu/Arch default).
    2. The symlink points under ``/usr/lib/systemd/`` (Fedora/RHEL).
    3. Neither (cloud-init / netplan writes a regular file) but the file's
       only nameserver is the systemd-resolved stub ``127.0.0.53`` AND the
       ``resolvectl`` binary exists. The 127.0.0.53 sentinel is the
       resolved-owned loopback — non-resolved resolvers don't use it.
    """
    if sys.platform != "linux":
        return False
    if not shutil.which("resolvectl"):
        return False
    try:
        target = Path("/etc/resolv.conf").resolve()
    except OSError:
        return False
    target_s = str(target)
    if any(target_s.startswith(p) for p in _RESOLVED_SYMLINK_PREFIXES):
        return True
    # Static file with 127.0.0.53: parse the first uncommented `nameserver`
    # directive. Any other resolver (1.1.1.1, 8.8.8.8, the box's LAN dnsmasq)
    # → not resolved → fall back to the classic DNS= line.
    try:
        text = Path("/etc/resolv.conf").read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() == "nameserver":
                return parts[1] == "127.0.0.53"
    except OSError:
        return False
    return False


def _dns_lines_for(wg) -> str:
    """Render the ``[Interface]`` DNS block for the running environment."""
    if not wg.dns:
        return ""
    if _systemd_resolved_active():
        # Drive systemd-resolved directly: %i is the interface name, "~." adds
        # the tunnel as the default route for every domain. Revert lives in
        # PreDown so the interface still exists when resolvectl needs it.
        dns_str = " ".join(wg.dns)
        return (
            f"PostUp = resolvectl dns %i {dns_str}\n"
            f"PostUp = resolvectl domain %i ~.\n"
            f"PreDown = resolvectl revert %i\n"
        )
    return f"DNS = {', '.join(wg.dns)}\n"


def build_wg_conf(config: ClientConfig, extra_bypass: list[str] | None = None) -> str:
    wg = config.wireguard
    tunnel = config.tunnel
    # Always exclude the server endpoint itself from the tunnel. If it stayed
    # inside AllowedIPs, wstunnel's own connection to the server would be routed
    # back through the tunnel → loop, the WG handshake never completes. Resolved
    # at connect time (see _resolve_bypass_networks) so a domain endpoint works
    # too. Belt-and-suspenders on top of the server-provided bypass_ips.
    #
    # `extra_bypass` carries the union of every alternate front the fallback
    # ladder might dial (CDN anycast, a proxy, alt-port hosts). Excluding them
    # all up front means switching rungs never needs a live route change — WG is
    # installed once and only the wstunnel process is relaunched per rung.
    bypass = list(config.routing.bypass_ips)
    if config.server.endpoint:
        bypass.append(config.server.endpoint)
    if extra_bypass:
        bypass.extend(extra_bypass)
    allowed_ips = _allowed_ips_excluding(bypass) if bypass else "0.0.0.0/0"
    dns_line = _dns_lines_for(wg)
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
