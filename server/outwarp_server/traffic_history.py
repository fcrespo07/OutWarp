"""Per-peer rx/tx snapshots persisted to SQLite for the dashboard sparkline.

A snapshot row stores raw cumulative counters (what `wg show <iface> dump`
reports). Deltas are computed at read time with window functions — counters
reset on interface restart, so we clamp negative deltas to zero rather than
recording a fake gigabyte.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from outwarp_server.config import ServerConfig
from outwarp_server.wireguard import get_live_peers

log = logging.getLogger(__name__)


# Where the history lived until 0.16: outside the config dir, so in a pod
# the `serve` container wrote a database the panel container never saw, and
# the pod's filesystem lost it on every restart (B-041).
LEGACY_DB_PATH = Path("/var/lib/outwarp/traffic.sqlite")
DB_FILENAME = "traffic.sqlite"
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


def traffic_db_path(config_dir: Path | None = None) -> Path:
    """The history database: next to the server config, so every process
    reading that config (`serve`, the panel, the TUI) shares one history
    and a container keeps it on its config volume."""
    if config_dir is None:
        from outwarp_server.config import default_config_dir

        config_dir = default_config_dir()
    return Path(config_dir) / DB_FILENAME


def _adopt_legacy_db(target: Path, legacy: Path = LEGACY_DB_PATH) -> None:
    """Copy a pre-0.17 database into its new home once. Copied, not moved:
    another process may still have the old one open, and the copy goes via a
    temp file so a reader never sees half a database."""
    if target.exists() or target == legacy or not legacy.is_file():
        return
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, tmp)
        os.replace(tmp, target)
        log.info("Traffic history moved from %s to %s", legacy, target)
    except OSError as exc:
        log.warning("Could not adopt the old traffic history %s: %s", legacy, exc)
        tmp.unlink(missing_ok=True)


class TrafficHistory:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        config: ServerConfig | None = None,
        peer_source=None,
    ) -> None:
        if db_path is None:
            db_path = traffic_db_path()
            _adopt_legacy_db(db_path)
        self._db_path = Path(db_path)
        self._config = config
        # Source of {public_key: LivePeer} — injectable so tests can stub it
        # without needing a real `wg` binary.
        self._peer_source = peer_source or (lambda: get_live_peers())
        self._lock = threading.Lock()
        self._ensure_schema()

    @classmethod
    def for_config_dir(
        cls, config_dir: Path, *, config: ServerConfig | None = None,
    ) -> TrafficHistory:
        path = traffic_db_path(config_dir)
        _adopt_legacy_db(path)
        return cls(path, config=config)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        # `serve` writes while the panel (another process, maybe another
        # container on the same volume) reads: wait out the other's lock.
        return sqlite3.connect(self._db_path, isolation_level=None, timeout=5)

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

    def series(
        self, window_seconds: int, bucket_seconds: int, *, now: int | None = None,
    ) -> dict:
        """Everything the panel's Traffic screen draws for one window.

        Buckets are dense (an empty stretch is a run of zeros, not a missing
        bar) and aligned to `bucket_seconds`, the newest one holding `now`.
        Each byte delta between two snapshots of a peer is counted in the
        bucket of the later snapshot; a counter that went backwards (the
        interface restarted) counts as zero. `peak_bps` is the highest
        all-peers rate between two consecutive snapshots, not a bucket
        average. `covered_seconds` is how much of the window actually has
        snapshots, so a fresh install does not report its first ten minutes
        averaged over a day.
        """
        now = int(time.time()) if now is None else int(now)
        n = max(1, window_seconds // bucket_seconds)
        end = (now // bucket_seconds + 1) * bucket_seconds
        start = end - n * bucket_seconds
        rx = [0] * n
        tx = [0] * n
        per_key: dict[str, list[int]] = {}
        rate_at: dict[int, float] = {}
        first_ts = last_ts = None
        with self._lock:
            try:
                with self._connect() as conn:
                    # Look back a little before the window so its first
                    # snapshot still has a predecessor to diff against.
                    cur = conn.execute(
                        """
                        WITH deltas AS (
                            SELECT ts, public_key,
                                   rx_bytes - LAG(rx_bytes) OVER w AS d_rx,
                                   tx_bytes - LAG(tx_bytes) OVER w AS d_tx,
                                   ts - LAG(ts) OVER w AS dt
                            FROM snapshot
                            WHERE ts >= ?
                            WINDOW w AS (PARTITION BY public_key ORDER BY ts)
                        )
                        SELECT ts, public_key, d_rx, d_tx, dt FROM deltas
                        WHERE ts >= ? AND dt IS NOT NULL
                        """,
                        (start - 6 * 3600, start),
                    )
                    rows = cur.fetchall()
                    first_ts, last_ts = conn.execute(
                        "SELECT MIN(ts), MAX(ts) FROM snapshot WHERE ts >= ?", (start,),
                    ).fetchone()
            except sqlite3.Error as exc:
                log.warning("Traffic series read failed: %s", exc)
                rows = []
        for ts, public_key, d_rx, d_tx, dt in rows:
            d_rx = max(0, int(d_rx or 0))
            d_tx = max(0, int(d_tx or 0))
            i = (int(ts) - start) // bucket_seconds
            if 0 <= i < n:
                rx[i] += d_rx
                tx[i] += d_tx
            totals = per_key.setdefault(public_key, [0, 0])
            totals[0] += d_rx
            totals[1] += d_tx
            if dt and dt > 0:
                rate_at[int(ts)] = rate_at.get(int(ts), 0.0) + (d_rx + d_tx) / dt
        covered = 0 if first_ts is None else max(0, now - max(int(first_ts), now - window_seconds))
        return {
            "bucket_seconds": bucket_seconds,
            "start": start,
            "rx": rx,
            "tx": tx,
            "per_key": per_key,
            "peak_bps": int(max(rate_at.values(), default=0.0)),
            "covered_seconds": covered,
            "first_ts": None if first_ts is None else int(first_ts),
            "last_ts": None if last_ts is None else int(last_ts),
        }

    def bind_config(self, config: ServerConfig | None) -> None:
        self._config = config

    def client_names(self) -> dict[str, str]:
        if self._config is None:
            return {}
        return {c.public_key: c.name for c in self._config.clients}

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
                    # Sum per-step LAG() deltas (clamping resets to zero) rather
                    # than MAX-MIN: an interface restart drops the counter back
                    # near zero, so MAX-MIN would report almost the peer's whole
                    # lifetime transfer as if it happened inside the window.
                    cur = conn.execute(
                        """
                        WITH deltas AS (
                            SELECT public_key,
                                   rx_bytes - COALESCE(LAG(rx_bytes) OVER w, rx_bytes) AS d_rx,
                                   tx_bytes - COALESCE(LAG(tx_bytes) OVER w, tx_bytes) AS d_tx
                            FROM snapshot
                            WHERE ts >= ?
                            WINDOW w AS (PARTITION BY public_key ORDER BY ts)
                        )
                        SELECT public_key,
                               SUM(CASE WHEN d_rx > 0 THEN d_rx ELSE 0 END) AS d_rx,
                               SUM(CASE WHEN d_tx > 0 THEN d_tx ELSE 0 END) AS d_tx
                        FROM deltas
                        GROUP BY public_key
                        ORDER BY (d_rx + d_tx) DESC
                        LIMIT ?
                        """,
                        (since, limit),
                    )
                    raw = cur.fetchall()
            except sqlite3.Error as exc:
                log.warning("Traffic top_talkers read failed: %s", exc)
                return []
        name_for = self.client_names()
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
        # First snapshot right away: a server restarted every few minutes
        # (or a fresh one) would otherwise never record anything.
        while True:
            try:
                self._history.snapshot()
            except Exception:
                log.exception("Traffic history scheduler tick failed")
            if self._stop.wait(self._interval):
                return


def build_scheduler(
    config: ServerConfig,
    *,
    db_path: Path | None = None,
    config_dir: Path | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> _SnapshotScheduler:
    if db_path is None and config_dir is not None:
        history = TrafficHistory.for_config_dir(config_dir, config=config)
    else:
        history = TrafficHistory(db_path, config=config)
    log.info("Traffic history: %s (a snapshot every %ds)", history.db_path, int(interval))
    return _SnapshotScheduler(history, interval)
