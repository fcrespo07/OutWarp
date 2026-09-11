from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from outwarp_server.client_store import ClientStore
from outwarp_server.config import ClientEntry


def _entry(name: str, address: str, **overrides) -> ClientEntry:
    overrides.setdefault("public_key", "pub-" + name)
    return ClientEntry(name=name, address=address, **overrides)


class TestSchemaAndBasics:
    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are not enforced on NTFS")
    def test_creates_db_file_at_0o600(self, tmp_path: Path) -> None:
        db_path = tmp_path / "clients.sqlite"
        ClientStore(db_path)
        assert db_path.exists()
        assert (db_path.stat().st_mode & 0o777) == 0o600

    def test_list_active_empty_on_fresh_store(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        assert store.list_active() == []
        assert store.get("nobody") is None

    def test_insert_then_get_roundtrips(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(_entry("laptop", "10.0.0.2/32"), conn=conn, created_at="2026-01-01")
        got = store.get("laptop")
        assert got is not None
        assert got.name == "laptop"
        assert got.address == "10.0.0.2/32"
        assert got.state == "active"


class TestSoftDelete:
    """CONCEPTO-D: revoking must not destroy the row — otherwise "never
    enrolled" and "enrolled, then revoked" stay indistinguishable forever."""

    def test_revoked_client_excluded_from_list_active(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(_entry("laptop", "10.0.0.2/32"), conn=conn)
            store.insert(_entry("phone", "10.0.0.3/32"), conn=conn)
            store.soft_delete("laptop", conn=conn)

        assert {c.name for c in store.list_active()} == {"phone"}

    def test_revoked_client_still_present_in_list_all(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(_entry("laptop", "10.0.0.2/32"), conn=conn)
            store.soft_delete("laptop", conn=conn)

        all_rows = store.list_all()
        assert {c.name for c in all_rows} == {"laptop"}
        assert all_rows[0].state == "revoked"

    def test_never_enrolled_vs_enrolled_then_revoked_are_distinguishable(
        self, tmp_path: Path,
    ) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(
                _entry("pending", "10.0.0.2/32", public_key=""), conn=conn,
            )
            store.insert(_entry("done", "10.0.0.3/32"), conn=conn)
            store.soft_delete("pending", conn=conn)
            store.soft_delete("done", conn=conn)

        by_name = {c.name: c for c in store.list_all()}
        assert by_name["pending"].public_key == ""
        assert by_name["done"].public_key == "pub-done"
        assert by_name["pending"].state == by_name["done"].state == "revoked"

    def test_freed_ip_is_immediately_reusable(self, tmp_path: Path) -> None:
        """Matches the pre-CONCEPTO-A hard-delete behaviour: list_active()
        (what add_client's IP allocator reads) must not still show the
        revoked client's address as taken."""
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(_entry("laptop", "10.0.0.2/32"), conn=conn)
            store.soft_delete("laptop", conn=conn)

        allocated = [c.address for c in store.list_active()]
        assert "10.0.0.2/32" not in allocated


class TestMigration:
    def test_migrates_json_clients_once(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        clients = [_entry("laptop", "10.0.0.2/32"), _entry("phone", "10.0.0.3/32")]
        store.migrate_from_json(clients)
        assert {c.name for c in store.list_active()} == {"laptop", "phone"}

    def test_migration_is_a_noop_once_the_table_has_rows(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        store.migrate_from_json([_entry("laptop", "10.0.0.2/32")])
        with store.transaction() as conn:
            store.soft_delete("laptop", conn=conn)
        # A second migration attempt (e.g. a stale in-memory ServerConfig still
        # carrying the old JSON clients array) must not resurrect the revoked row.
        store.migrate_from_json([_entry("laptop", "10.0.0.2/32")])
        assert store.list_active() == []

    def test_empty_json_clients_is_a_noop(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        store.migrate_from_json([])
        assert store.list_all() == []

    def test_repeated_migration_does_not_take_the_write_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After the first successful migration, every subsequent
        `ServerConfig.load()` calls this with a non-empty list again (it
        always round-trips `list_active()` back into the JSON `clients`
        array) — that must stay a lock-free read, not a `BEGIN IMMEDIATE`
        transaction, or every load serializes against concurrent writers."""
        store = ClientStore(tmp_path / "clients.sqlite")
        store.migrate_from_json([_entry("laptop", "10.0.0.2/32")])

        def _boom():
            raise AssertionError("migrate_from_json took the write lock on a no-op call")

        monkeypatch.setattr(store, "transaction", _boom)
        store.migrate_from_json([_entry("laptop", "10.0.0.2/32")])


class TestConcurrentInsert:
    """CONCEPTO-A: the actual point of moving off the JSON+flock bridge — two
    writers computing "what's allocated" and inserting must not be able to
    race each other, closing the FIX-04 IP-collision bug by construction
    instead of by callers remembering to hold a lock."""

    def _add_with_naive_allocator(self, store: ClientStore, name: str) -> None:
        """Mirrors operations.add_client's shape: read what's active inside
        the transaction, pick the next free slot in a small pool, insert."""
        pool = [f"10.0.0.{i}/32" for i in range(2, 10)]
        with store.transaction() as conn:
            allocated = {c.address for c in store.list_active(conn)}
            free = next(a for a in pool if a not in allocated)
            store.insert(_entry(name, free), conn=conn)

    def test_n_concurrent_inserts_yield_n_distinct_addresses(self, tmp_path: Path) -> None:
        store = ClientStore(tmp_path / "clients.sqlite")
        n = 8
        errors: list[BaseException] = []

        def _worker(i: int) -> None:
            try:
                self._add_with_naive_allocator(store, f"client-{i}")
            except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        rows = store.list_active()
        assert len(rows) == n
        addresses = [c.address for c in rows]
        assert len(addresses) == len(set(addresses)), (
            f"duplicate address allocated across concurrent inserts: {addresses}"
        )
