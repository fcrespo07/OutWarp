"""Per-second tunnel telemetry for the TUI dashboard.

The TUI needs rates (B/s) and a rolling history to feed Textual's `Sparkline`.
`wg show <iface> dump` reports cumulative counters; we keep the previous sample
to compute deltas, and gate negative deltas (interface restart) to zero.
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TunnelStats:
    rx_bytes_total: int
    tx_bytes_total: int
    rx_rate_bps: float
    tx_rate_bps: float
    last_handshake_age_s: int | None
    latency_ms: float | None


_DEFAULT_WIN_WG = Path(r"C:\Program Files\WireGuard\wg.exe")


def _find_wg() -> Path | None:
    if sys.platform == "win32" and _DEFAULT_WIN_WG.exists():
        return _DEFAULT_WIN_WG
    found = shutil.which("wg")
    return Path(found) if found else None


def _read_wg_transfer(iface: str) -> tuple[int, int, int | None] | None:
    """Return (rx_total, tx_total, last_handshake_ts) or None if unavailable."""
    wg = _find_wg()
    if wg is None:
        return None
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [str(wg), "show", iface, "dump"],
            capture_output=True, text=True, check=False, timeout=2, **extra,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    parts = lines[1].split("\t")
    if len(parts) < 8:
        return None
    _pub, _psk, _ep, _allowed, handshake, rx, tx, _ka = parts[:8]
    try:
        hs = int(handshake)
    except ValueError:
        hs = 0
    rx_n = int(rx) if rx.isdigit() else 0
    tx_n = int(tx) if tx.isdigit() else 0
    return rx_n, tx_n, hs if hs > 0 else None


def _ping_once(host: str, *, timeout_s: float = 1.0) -> float | None:
    """Return round-trip ms or None on failure."""
    ping = shutil.which("ping")
    if ping is None:
        return None
    if sys.platform == "win32":
        cmd = [ping, "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        cmd = [ping, "-c", "1", "-W", str(max(1, int(timeout_s))), host]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout_s + 1.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    # Look for "time=12.3 ms" or "time=12.3ms" (Linux) / "time=12ms" (Windows).
    for token in proc.stdout.split():
        if token.startswith("time=") or token.startswith("time<"):
            value = token.split("=", 1)[-1].split("<", 1)[-1]
            value = value.rstrip("ms").rstrip()
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _resolve_host(host: str) -> str:
    """Pre-resolve a hostname so ping doesn't pay DNS on every sample."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


class StatsSampler:
    """Maintain a rolling history of throughput and latency samples."""

    def __init__(
        self,
        iface: str,
        peer_endpoint_host: str,
        history: int = 60,
        *,
        transfer_source=None,
        latency_source=None,
        clock=time.monotonic,
    ) -> None:
        self._iface = iface
        self._peer = _resolve_host(peer_endpoint_host)
        self._history = history
        self._transfer_source = transfer_source or (lambda: _read_wg_transfer(self._iface))
        self._latency_source = latency_source or (lambda: _ping_once(self._peer))
        self._clock = clock
        self._last_sample: tuple[float, int, int] | None = None
        self._rx_bps: deque[float] = deque(maxlen=history)
        self._tx_bps: deque[float] = deque(maxlen=history)
        self._ping_ms: deque[float] = deque(maxlen=history)

    def sample(self) -> TunnelStats:
        now = self._clock()
        transfer = self._transfer_source()
        if transfer is None:
            return TunnelStats(0, 0, 0.0, 0.0, None, None)
        rx_total, tx_total, last_hs = transfer
        rx_rate = 0.0
        tx_rate = 0.0
        if self._last_sample is not None:
            prev_t, prev_rx, prev_tx = self._last_sample
            dt = max(now - prev_t, 1e-6)
            rx_rate = max(0.0, (rx_total - prev_rx) / dt)
            tx_rate = max(0.0, (tx_total - prev_tx) / dt)
        self._last_sample = (now, rx_total, tx_total)
        self._rx_bps.append(rx_rate)
        self._tx_bps.append(tx_rate)

        latency = self._latency_source()
        if latency is not None:
            self._ping_ms.append(latency)

        handshake_age = None
        if last_hs is not None:
            handshake_age = max(0, int(time.time()) - last_hs)
        return TunnelStats(
            rx_bytes_total=rx_total,
            tx_bytes_total=tx_total,
            rx_rate_bps=rx_rate,
            tx_rate_bps=tx_rate,
            last_handshake_age_s=handshake_age,
            latency_ms=latency,
        )

    def history_rx_bps(self) -> list[float]:
        return list(self._rx_bps)

    def history_tx_bps(self) -> list[float]:
        return list(self._tx_bps)

    def history_ping_ms(self) -> list[float]:
        return list(self._ping_ms)
