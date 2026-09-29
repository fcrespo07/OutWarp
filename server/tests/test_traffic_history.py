from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.traffic_history import TrafficHistory
from outwarp_server.wireguard import LivePeer


def _peer(public_key: str, rx: int, tx: int) -> LivePeer:
    return LivePeer(
        public_key=public_key,
        endpoint="1.2.3.4:51820",
        allowed_ips="10.13.13.5/32",
        latest_handshake=int(time.time()),
        transfer_rx=rx,
        transfer_tx=tx,
    )


def _config(clients: list[ClientEntry] | None = None) -> ServerConfig:
    return ServerConfig(
        schema_version=1, endpoint="e", port=443, http_upgrade_path_prefix="x",
        cert_path="/tmp/c", key_path="/tmp/k", cert_fingerprint_sha256="AB:" * 31 + "AB",
        wg_private_key="p", wg_public_key="P",
        subnet="10.13.13.0/24", server_address="10.13.13.1/24",
        wg_listen_port=51820, clients=clients or [],
    )


def test_snapshot_writes_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    peers = {"k1": _peer("k1", 100, 200), "k2": _peer("k2", 300, 400)}
    h = TrafficHistory(db, peer_source=lambda: peers)
    written = h.snapshot()
    assert written == 2
    with sqlite3.connect(db) as conn:
        rows = list(conn.execute("SELECT public_key, rx_bytes, tx_bytes FROM snapshot"))
    assert set(rows) == {("k1", 100, 200), ("k2", 300, 400)}


def test_snapshot_no_peers_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db, peer_source=lambda: {})
    assert h.snapshot() == 0


def test_hourly_buckets_returns_deltas(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db)
    now = int(time.time())
    # Inject two samples ~10 minutes apart for one peer.
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now - 600, "k", 1000, 2000))
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now,       "k", 5000, 9000))
    buckets = h.hourly_buckets(hours=2)
    assert len(buckets) >= 1
    total_rx = sum(b[1] for b in buckets)
    total_tx = sum(b[2] for b in buckets)
    # Delta is (5000-1000)=4000 rx and (9000-2000)=7000 tx.
    assert total_rx == 4000
    assert total_tx == 7000


def test_hourly_buckets_clamps_counter_reset(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db)
    now = int(time.time())
    with sqlite3.connect(db) as conn:
        # Counter falls (interface restart): delta is negative — must clamp to 0.
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now - 600, "k", 10000, 10000))
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now,       "k", 50, 50))
    buckets = h.hourly_buckets(hours=2)
    total = sum(b[1] + b[2] for b in buckets)
    assert total == 0


def test_top_talkers_orders_by_total(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    config = _config(clients=[
        ClientEntry(name="alice", public_key="kA", address="10.13.13.2/32"),
        ClientEntry(name="bob",   public_key="kB", address="10.13.13.3/32"),
    ])
    h = TrafficHistory(db, config=config)
    now = int(time.time())
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now - 600, "kA", 0,     0))
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now,       "kA", 100, 100))
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now - 600, "kB", 0, 0))
        conn.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?)", (now,       "kB", 9000, 9000))
    talkers = h.top_talkers(since_seconds=3600)
    assert [t["name"] for t in talkers[:2]] == ["bob", "alice"]


def test_retention_drops_old_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db, peer_source=lambda: {"k": _peer("k", 1, 1)})
    now = int(time.time())
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO snapshot VALUES (?, ?, ?, ?)",
            (now - 30 * 86400, "old", 5, 5),
        )
    h.snapshot()
    with sqlite3.connect(db) as conn:
        rows = list(conn.execute("SELECT public_key FROM snapshot"))
    assert ("old",) not in rows


# ── B-041: one database next to the config, a dense series for the panel ──

def test_the_database_lives_next_to_the_config(tmp_path: Path) -> None:
    from outwarp_server.traffic_history import traffic_db_path

    h = TrafficHistory.for_config_dir(tmp_path)
    assert h.db_path == traffic_db_path(tmp_path) == tmp_path / "traffic.sqlite"
    assert h.db_path.exists()


def test_an_old_database_is_adopted_once(tmp_path: Path, monkeypatch) -> None:
    from outwarp_server import traffic_history

    legacy = tmp_path / "var" / "traffic.sqlite"
    TrafficHistory(legacy, peer_source=lambda: {"k": _peer("k", 5, 6)}).snapshot()
    monkeypatch.setattr(traffic_history, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(traffic_history._adopt_legacy_db, "__defaults__", (legacy,))
    cfg = tmp_path / "cfg"
    h = TrafficHistory.for_config_dir(cfg)
    with sqlite3.connect(h.db_path) as conn:
        assert list(conn.execute("SELECT public_key FROM snapshot")) == [("k",)]
    # The new one is now authoritative: a second open does not copy again.
    with sqlite3.connect(h.db_path) as conn:
        conn.execute("DELETE FROM snapshot")
    h2 = TrafficHistory.for_config_dir(cfg)
    with sqlite3.connect(h2.db_path) as conn:
        assert list(conn.execute("SELECT * FROM snapshot")) == []
    assert legacy.exists()


def test_two_processes_share_one_history(tmp_path: Path) -> None:
    """`serve` writes, the panel (another process) reads: the same file."""
    writer = TrafficHistory.for_config_dir(tmp_path, config=None)
    writer._peer_source = lambda: {"k": _peer("k", 0, 0)}
    writer.snapshot()
    reader = TrafficHistory.for_config_dir(tmp_path)
    assert reader.series(3600, 60)["first_ts"] is not None


def _insert(db: Path, rows) -> None:
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO snapshot VALUES (?, ?, ?, ?)", rows)


def test_series_is_dense_and_puts_each_delta_in_its_bucket(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db)
    now = 1_000_000_000 - 30  # 30 s before a minute boundary
    _insert(db, [
        (now - 600, "k", 1000, 2000),
        (now - 540, "k", 7000, 2600),
        (now - 60, "k", 7000, 2600),
        (now, "k", 8000, 3600),
    ])
    s = h.series(3600, 60, now=now)
    assert len(s["rx"]) == len(s["tx"]) == 60
    assert sum(s["rx"]) == 7000 and sum(s["tx"]) == 1600
    assert s["rx"][-1] == 1000                 # newest bucket holds `now`
    assert s["rx"][-1 - 9] == 6000             # 540 s earlier
    assert s["rx"].count(0) == 58              # quiet minutes are zeros
    assert s["peak_bps"] == (6000 + 600) // 60
    assert s["covered_seconds"] == 600
    assert s["per_key"] == {"k": [7000, 1600]}


def test_series_diffs_the_first_snapshot_against_the_one_before_the_window(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db)
    now = 1_000_000_000
    _insert(db, [(now - 3700, "k", 0, 0), (now - 3500, "k", 500, 500)])
    s = h.series(3600, 60, now=now)
    assert sum(s["rx"]) == 500


def test_series_on_an_empty_history_says_so(tmp_path: Path) -> None:
    s = TrafficHistory(tmp_path / "t.sqlite").series(86400, 900, now=1_000_000_000)
    assert len(s["rx"]) == 96 and not any(s["rx"])
    assert s["first_ts"] is None and s["covered_seconds"] == 0 and s["peak_bps"] == 0


def test_series_clamps_a_counter_reset(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    h = TrafficHistory(db)
    now = 1_000_000_000
    _insert(db, [(now - 120, "k", 10_000, 10_000), (now - 60, "k", 10, 10), (now, "k", 110, 60)])
    s = h.series(3600, 60, now=now)
    assert sum(s["rx"]) == 100 and sum(s["tx"]) == 50


def test_scheduler_snapshots_as_soon_as_it_starts(tmp_path: Path) -> None:
    from outwarp_server.traffic_history import _SnapshotScheduler

    h = TrafficHistory(tmp_path / "t.sqlite", peer_source=lambda: {"k": _peer("k", 1, 1)})
    sched = _SnapshotScheduler(h, interval=3600)
    sched.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            with sqlite3.connect(h.db_path) as conn:
                if list(conn.execute("SELECT 1 FROM snapshot")):
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("no snapshot at start")
    finally:
        sched.stop()
