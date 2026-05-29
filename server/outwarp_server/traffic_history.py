"""Per-peer rx/tx snapshots persisted to SQLite for the dashboard sparkline.

A snapshot row stores raw cumulative counters (what `wg show <iface> dump`
reports). Deltas are computed at read time with window functions — counters
reset on interface restart, so we clamp negative deltas to zero rather than
recording a fake gigabyte.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from outwarp_server.config import ServerConfig
from outwarp_server.wireguard import LivePeer, get_live_peers

log = logging.getLogger(__name__)


DEFAULT_DB_PATH = Path("/var/lib/outwarp/traffic.sqlite")
_RETENTION_SECONDS = 7 * 24 * 3600
DEFAULT_INTERVAL_SECONDS = 60


_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    ts INTEGER NOT NULL,
    public_key TEXT NOT NULL,
    rx_bytes INTEGER NOT NULL,
    tx_bytes INTEGER NOT NULL,
    PRIMARY KEY (ts, public_key)
);
CREATE INDEX IF NOT EXISTS idx_ts ON snapshot(ts);
"""


class TrafficHistory:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        config: ServerConfig | None = None,
        peer_source=None,
    ) -> None:
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._config = config
        # Source of {public_key: LivePeer} — injectable so tests can stub it
        # without needing a real `wg` binary.
        self._peer_source = peer_source or (lambda: get_live_peers())
        self._lock = threading.Lock()
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, isolation_level=None)

    def _ensure_schema(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Cannot create traffic history dir %s: %s", self._db_path.parent, exc)
            return
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            log.warning("Cannot init traffic history schema: %s", exc)

    def snapshot(self) -> int:
        """Persist current counters. Returns number of peer rows written."""
        try:
            peers = self._peer_source()
        except Exception as exc:
            log.warning("Traffic snapshot: failed to read live peers: %s", exc)
            return 0
        if not peers:
            return 0
        ts = int(time.time())
        rows = [
            (ts, p.public_key, p.transfer_rx, p.transfer_tx)
            for p in peers.values()
        ]
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO snapshot (ts, public_key, rx_bytes, tx_bytes) "
                        "VALUES (?, ?, ?, ?)",
                        rows,
                    )
                    conn.execute(
                        "DELETE FROM snapshot WHERE ts < ?",
                        (ts - _RETENTION_SECONDS,),
                    )
            except sqlite3.Error as exc:
                log.warning("Traffic snapshot write failed: %s", exc)
                return 0
        return len(rows)

    def hourly_buckets(self, hours: int = 24) -> list[tuple[int, int, int]]:
        """Return [(hour_start_ts, sum_rx_delta, sum_tx_delta), ...] newest last.

        Deltas are taken per-peer with LAG() and summed inside each hour bucket;
        counter resets (delta < 0) clamp to zero so an interface restart doesn't
        produce a phantom spike.
        """
        now = int(time.time())
        since = now - hours * 3600
        with self._lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        WITH deltas AS (
                            SELECT
                                (ts / 3600) * 3600 AS hour_ts,
                                public_key,
                                rx_bytes - COALESCE(LAG(rx_bytes) OVER w, rx_bytes) AS d_rx,
                                tx_bytes - COALESCE(LAG(tx_bytes) OVER w, tx_bytes) AS d_tx
                            FROM snapshot
                            WHERE ts >= ?
                            WINDOW w AS (PARTITION BY public_key ORDER BY ts)
                        )
                        SELECT hour_ts,
                               SUM(CASE WHEN d_rx > 0 THEN d_rx ELSE 0 END) AS rx,
                               SUM(CASE WHEN d_tx > 0 THEN d_tx ELSE 0 END) AS tx
                        FROM deltas
                        GROUP BY hour_ts
                        ORDER BY hour_ts
                        """,
                        (since,),
                    )
                    return [(int(r[0]), int(r[1] or 0), int(r[2] or 0)) for r in cur.fetchall()]
            except sqlite3.Error as exc:
                log.warning("Traffic hourly read failed: %s", exc)
                return []

    def top_talkers(
        self, since_seconds: int = 3600, limit: int = 5,
    ) -> list[dict]:
        """Return [{public_key, name, rx_delta, tx_delta}, ...] sorted by rx+tx.

        `name` is filled from the bound ServerConfig (if any), falling back to
        the truncated public key for peers that have been revoked between
        snapshots but still appear in the window.
        """
        now = int(time.time())
        since = now - since_seconds
        with self._lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        WITH first_last AS (
                            SELECT public_key,
                                   MIN(rx_bytes) AS rx_lo, MAX(rx_bytes) AS rx_hi,
                                   MIN(tx_bytes) AS tx_lo, MAX(tx_bytes) AS tx_hi
                            FROM snapshot
                            WHERE ts >= ?
                            GROUP BY public_key
                        )
                        SELECT public_key, (rx_hi - rx_lo) AS d_rx, (tx_hi - tx_lo) AS d_tx
                        FROM first_last
                        ORDER BY (d_rx + d_tx) DESC
                        LIMIT ?
                        """,
                        (since, limit),
                    )
                    raw = cur.fetchall()
            except sqlite3.Error as exc:
                log.warning("Traffic top_talkers read failed: %s", exc)
                return []
        name_for: dict[str, str] = {}
        if self._config is not None:
            name_for = {c.public_key: c.name for c in self._config.clients}
        out: list[dict] = []
        for public_key, d_rx, d_tx in raw:
            out.append({
                "public_key": public_key,
                "name": name_for.get(public_key, public_key[:8] + "…"),
                "rx_delta": int(d_rx or 0),
                "tx_delta": int(d_tx or 0),
            })
        return out


class _SnapshotScheduler:
    """Background thread that drives TrafficHistory.snapshot() every N seconds."""

    def __init__(self, history: TrafficHistory, interval: float) -> None:
        self._history = history
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="outwarp-traffic-history",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def tick(self) -> int:
        """Force a single snapshot. Used by tests."""
        return self._history.snapshot()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._history.snapshot()
            except Exception:
                log.exception("Traffic history scheduler tick failed")


def build_scheduler(
    config: ServerConfig,
    *,
    db_path: Path | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> _SnapshotScheduler:
    history = TrafficHistory(db_path, config=config)
    return _SnapshotScheduler(history, interval)
