from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from outwarp_server.config import ServerConfig

log = logging.getLogger(__name__)


class WireGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class LivePeer:
    """Snapshot of a peer's runtime state from `wg show <iface> dump`."""
    public_key: str
    endpoint: str | None
    allowed_ips: str
    latest_handshake: int | None  # unix timestamp; None if never
    transfer_rx: int  # bytes received from peer
    transfer_tx: int  # bytes sent to peer


def _find_wg_bin() -> Path | None:
    """Locate the wg binary, trying common hard-coded paths as fallback."""
    found = __import__("shutil").which("wg")
    if found:
        return Path(found)
    for candidate in ("/usr/bin/wg", "/usr/local/bin/wg", "/sbin/wg"):
        p = Path(candidate)
        if p.exists():
            return p
    return None


def get_live_peers(interface: str = "wg0", wg_bin: Path | None = None) -> dict[str, LivePeer]:
    """Return public_key -> LivePeer for every peer on the running interface.

    Returns an empty dict if the interface is down or `wg` fails — callers
    should treat absence of data as "no live state available", not as error.
    """
    resolved = wg_bin or _find_wg_bin()
    if resolved is None:
        log.warning("get_live_peers: wg binary not found in PATH or common locations")
        return {}
    wg = str(resolved)
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [wg, "show", interface, "dump"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            **extra,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("get_live_peers: wg command failed: %s", exc)
        return {}
    if result.returncode != 0:
        log.warning(
            "get_live_peers: 'wg show %s dump' exited %d — %s",
            interface, result.returncode,
            result.stderr.strip() or "(no stderr)",
        )
        return {}

    peers: dict[str, LivePeer] = {}
    lines = result.stdout.strip().split("\n")
    # First line is the interface itself (private_key, public_key, listen_port, fwmark);
    # subsequent lines are peers.
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        public_key, _preshared, endpoint, allowed_ips, handshake, rx, tx, _keepalive = parts[:8]
        try:
            handshake_int = int(handshake)
        except ValueError:
            handshake_int = 0
        peers[public_key] = LivePeer(
            public_key=public_key,
            endpoint=endpoint if endpoint and endpoint != "(none)" else None,
            allowed_ips=allowed_ips,
            latest_handshake=handshake_int if handshake_int > 0 else None,
            transfer_rx=int(rx) if rx.isdigit() else 0,
            transfer_tx=int(tx) if tx.isdigit() else 0,
        )
    return peers


def build_server_wg_conf_windows(config: ServerConfig) -> str:
    """Build the server-side WireGuard config for Windows.

    WireGuard for Windows does not support PostUp/PostDown scripts.
    NAT and IP forwarding are handled separately by WindowsServerPlatform.prepare_system().
    """
    lines = [
        "[Interface]",
        f"PrivateKey = {config.wg_private_key}",
        f"Address = {config.server_address}",
        f"ListenPort = {config.wg_listen_port}",
    ]

    for client in config.clients:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"# {client.name}")
        lines.append(f"PublicKey = {client.public_key}")
        lines.append(f"AllowedIPs = {client.address}")

    lines.append("")
    return "\n".join(lines)


def build_server_wg_conf(config: ServerConfig) -> str:
    """Build the server-side wg0.conf content."""
    subnet = config.subnet
    lines = [
        "[Interface]",
        f"PrivateKey = {config.wg_private_key}",
        f"Address = {config.server_address}",
        f"ListenPort = {config.wg_listen_port}",
        # Table=off: routing is handled by iptables MASQUERADE (PostUp), not wg-quick.
        # Without this, wg-quick modifies the kernel routing table and can accidentally
        # break the server's own default route (observed with NetworkManager / VirtualBox NAT).
        "Table = off",
        # Insert FORWARD rules at position 1 to run before ufw's default DROP policy.
        # Using -A (append) puts our ACCEPT after ufw's drop chain, silently blocking
        # client traffic even though ip_forward is enabled.
        f"PostUp = sysctl -w net.ipv4.ip_forward=1; "
        f"iptables -I FORWARD 1 -i %i -j ACCEPT; "
        f"iptables -I FORWARD 2 -o %i -j ACCEPT; "
        f"iptables -t nat -A POSTROUTING -s {subnet} -j MASQUERADE",
        f"PostDown = iptables -D FORWARD -i %i -j ACCEPT; "
        f"iptables -D FORWARD -o %i -j ACCEPT; "
        f"iptables -t nat -D POSTROUTING -s {subnet} -j MASQUERADE",
    ]

    for client in config.clients:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"# {client.name}")
        lines.append(f"PublicKey = {client.public_key}")
        lines.append(f"AllowedIPs = {client.address}")

    lines.append("")
    return "\n".join(lines)


def add_peer_live(
    public_key: str,
    allowed_ips: str,
    interface: str = "wg0",
    wg_bin: Path | None = None,
) -> None:
    """Hot-add a peer to a running WireGuard interface."""
    wg = str(wg_bin or "wg")
    try:
        subprocess.run(
            [wg, "set", interface, "peer", public_key, "allowed-ips", allowed_ips],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise WireGuardError(f"Failed to add peer: {exc.stderr.strip()}") from exc
    log.info("Added peer %s with allowed-ips %s", public_key[:16] + "...", allowed_ips)


def remove_peer_live(
    public_key: str,
    interface: str = "wg0",
    wg_bin: Path | None = None,
) -> None:
    """Hot-remove a peer from a running WireGuard interface."""
    wg = str(wg_bin or "wg")
    try:
        subprocess.run(
            [wg, "set", interface, "peer", public_key, "remove"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise WireGuardError(f"Failed to remove peer: {exc.stderr.strip()}") from exc
    log.info("Removed peer %s", public_key[:16] + "...")
