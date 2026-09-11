"""SQLite-backed client registry — CONCEPTO-A/D in OutWarp-fix-plan.md.

`ServerConfig.clients` used to be part of the same JSON blob as the server's
own secrets, rewritten whole on every mutation and guarded only by a
cross-process flock (`config.locked_config`) — a serialization bridge, not a
transaction. Two near-simultaneous `add_client` calls could still allocate the
same pool IP if the bridge were ever bypassed or raced at the SQL layer they
didn't have. This module gives the registry its own table, modeled on
`traffic_history.py`'s style, so the race is impossible by construction:
`transaction()` opens with `BEGIN IMMEDIATE`, which takes SQLite's write lock
before the caller's first SELECT, so a second writer blocks until the first
commits instead of reading a snapshot the first is about to invalidate.

CONCEPTO-D: revoking a client used to delete its row outright, so there was no
way to tell "never enrolled" from "enrolled once, then revoked" apart once it
happened. `soft_delete()` instead flips `state` to 'revoked'; `list_active()`
(what feeds `ServerConfig.clients`) filters those out so every existing
consumer sees exactly the set it always has, while `list_all()` still has the
row for anyone who needs the history later.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path

from outwarp_server.config import ClientEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    name TEXT PRIMARY KEY,
    public_key TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL,
    psk TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'active',
    enrolled_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
"""

_COLUMNS = "name, public_key, address, psk, expires_at, state, enrolled_at, created_at"


def _row_to_entry(row: tuple) -> ClientEntry:
    name, public_key, address, psk, expires_at, state, enrolled_at, _created_at = row
    return ClientEntry(
        name=name,
        public_key=public_key,
        address=address,
        psk=psk,
        expires_at=expires_at,
        state=state,
        enrolled_at=enrolled_at,
    )


class ClientStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, isolation_level=None, timeout=30)

    def _ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        existed = self._db_path.exists()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        if not existed:
            with contextlib.suppress(OSError):
                os.chmod(self._db_path, 0o600)

    @contextlib.contextmanager
    def transaction(self):
        """Open a connection with an immediately-held write lock.

        `BEGIN IMMEDIATE` (rather than the deferred transaction a bare
        `conn.execute(...)` would start) takes SQLite's RESERVED lock before
        this context's first SELECT — a concurrent `transaction()` in another
        connection blocks at its own `BEGIN IMMEDIATE` until this one commits
        or rolls back, so "read what's allocated, then insert" can never race.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def list_active(self, conn: sqlite3.Connection | None = None) -> list[ClientEntry]:
        return self._list(conn, where="state != 'revoked'")

    def list_all(self, conn: sqlite3.Connection | None = None) -> list[ClientEntry]:
        return self._list(conn, where="1")

    def _list(self, conn: sqlite3.Connection | None, *, where: str) -> list[ClientEntry]:
        owns_conn = conn is None
        c = conn or self._connect()
        try:
            cur = c.execute(f"SELECT {_COLUMNS} FROM clients WHERE {where} ORDER BY name")
            return [_row_to_entry(row) for row in cur.fetchall()]
        finally:
            if owns_conn:
                c.close()

    def get(self, name: str, conn: sqlite3.Connection | None = None) -> ClientEntry | None:
        owns_conn = conn is None
        c = conn or self._connect()
        try:
            cur = c.execute(f"SELECT {_COLUMNS} FROM clients WHERE name = ?", (name,))
            row = cur.fetchone()
            return _row_to_entry(row) if row else None
        finally:
            if owns_conn:
                c.close()

    def insert(
        self,
        entry: ClientEntry,
        *,
        conn: sqlite3.Connection,
        created_at: str = "",
        replace_revoked: bool = False,
    ) -> None:
        """Insert a new client row.

        `name` is the primary key, so a revoked row blocks re-registration of
        that name; with `replace_revoked` the revoked row is dropped first.
        An *active* row is never replaced — the caller checks that under the
        same transaction and raises.
        """
        if replace_revoked:
            conn.execute(
                "DELETE FROM clients WHERE name = ? AND state = 'revoked'", (entry.name,)
            )
        conn.execute(
            "INSERT INTO clients "
            "(name, public_key, address, psk, expires_at, state, enrolled_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.name, entry.public_key, entry.address, entry.psk, entry.expires_at,
                entry.state, entry.enrolled_at, created_at,
            ),
        )

    def mark_enrolled(
        self, name: str, public_key: str, *, enrolled_at: str, conn: sqlite3.Connection,
    ) -> None:
        conn.execute(
            "UPDATE clients SET public_key = ?, enrolled_at = ? WHERE name = ?",
            (public_key, enrolled_at, name),
        )

    def update_keys(
        self, name: str, public_key: str, psk: str, *, conn: sqlite3.Connection,
    ) -> None:
        """Rotate an existing client's WireGuard key + PSK. Leaves `enrolled_at`
        untouched — a rotation is the same enrolment, not a new one."""
        conn.execute(
            "UPDATE clients SET public_key = ?, psk = ? WHERE name = ?",
            (public_key, psk, name),
        )

    def soft_delete(self, name: str, *, conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE clients SET state = 'revoked' WHERE name = ?", (name,))

    def migrate_from_json(self, clients: list[ClientEntry]) -> None:
        """One-time import from the legacy JSON `clients` array.

        Idempotent and safe under concurrent callers: guarded by the same
        `BEGIN IMMEDIATE` transaction as every other write, with a row-count
        check inside it — a second process racing the very first load also
        finds the table already populated and no-ops.
        """
        if not clients:
            return
        with self.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
            if count:
                return
            for entry in clients:
                # entry.enrolled_at is whatever _parse_client_entry gave it —
                # "" for every pre-CONCEPTO-A config, since the field didn't
                # exist yet and that history genuinely isn't recoverable.
                self.insert(entry, conn=conn)
