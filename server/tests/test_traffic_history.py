from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

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
