from __future__ import annotations

import contextlib
import logging
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input

log = logging.getLogger(__name__)

_ONLINE_WINDOW_SECONDS = 180


class ClientsScreen(Screen):
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("r", "revoke", "Revoke"),
        Binding("slash", "focus_search", "Search"),
        Binding("escape", "back", "Back", priority=True),
        Binding("q", "quit", "Quit", priority=True),
        Binding("question_mark", "help", "Help"),
    ]

    def action_back(self) -> None:
        # If the search input has focus, defocus to the table instead of popping
        # — matches the convention in TUI editors / mutt where Esc unfocuses.
        try:
            table = self.query_one(DataTable)
            search = self.query_one("#search", Input)
        except Exception:
            self.app.pop_screen()
            return
        if self.focused is search:
            search.value = ""
            table.focus()
            self.refresh_table()
            return
        self.app.pop_screen()

    async def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.action_back()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="clients-shell"):
            yield Input(placeholder="search...", id="search")
            yield DataTable(id="table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("●", "name", "address", "status", "last hs", "rx", "tx", "endpoint")
        # Default focus on the table so single-key verbs (a, r, q, ?) work
        # without a leading Tab. Pressing `/` jumps focus into search.
        t.focus()
        self.set_interval(2.0, self.refresh_table)
        self.refresh_table()

    def refresh_table(self) -> None:
        from outwarp_server.wireguard import get_live_peers

        try:
            table = self.query_one(DataTable)
        except Exception:
            return
        # remember selected row index to restore after rebuild
        cursor = table.cursor_row
        table.clear()

        config = self.app.config
        peers = get_live_peers()
        now = int(time.time())
        search = self.query_one("#search", Input).value.strip().lower()

        for c in config.clients:
            if search and search not in c.name.lower():
                continue
            peer = peers.get(c.public_key)
            if peer is None:
                dot, status, hs, rx, tx, endpoint = "○", "unknown", "—", "—", "—", "—"
            elif peer.latest_handshake is None:
                dot, status, hs, rx, tx, endpoint = "○", "idle", "never", "0 B", "0 B", "—"
            else:
                age = now - peer.latest_handshake
                if age < _ONLINE_WINDOW_SECONDS:
                    dot, status = "●", "[#2ee0b3]online[/]"
                else:
                    dot, status = "◐", "[#ff9b4a]offline[/]"
                hs = _fmt_age(age)
                rx = _fmt_bytes(peer.transfer_rx)
                tx = _fmt_bytes(peer.transfer_tx)
                endpoint = peer.endpoint or "—"
            table.add_row(dot, c.name, c.address, status, hs, rx, tx, endpoint)

        if cursor is not None and cursor < table.row_count:
            with contextlib.suppress(Exception):
                table.move_cursor(row=cursor)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_table()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def _selected_name(self) -> str | None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        try:
            row = table.get_row_at(table.cursor_row)
        except Exception:
            return None
        return str(row[1]) if len(row) > 1 else None

    def action_add(self) -> None:
        from outwarp_server.tui.modals.add_client import AddClientModal
        self.app.push_screen(AddClientModal(), lambda _r: self.refresh_table())

    def action_revoke(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("Select a client first.", severity="warning")
            return

        from outwarp_server.tui.modals.confirm import ConfirmModal

        def _go(result: bool | None) -> None:
            if not result:
                return
            from outwarp_server import operations
            try:
                operations.revoke_client(
                    self.app.config, name, config_path=self.app.config_path,
                )
            except KeyError:
                self.notify(f"Client '{name}' not found.", severity="error")
                return
            # Refresh in-memory config from disk so subsequent refreshes are correct.
            self.app.reload_config()
            self.refresh_table()

        self.app.push_screen(
            ConfirmModal(
                title=f"Revoke '{name}'?",
                body="The client will lose access immediately.",
                ok_label="Revoke",
            ),
            _go,
        )

    def action_help(self) -> None:
        from outwarp_server.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


def _fmt_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"
