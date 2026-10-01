from __future__ import annotations

import contextlib
import logging
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input

from outwarp_server.i18n import t as tr
from outwarp_server.tui.tokens import OK, WARN

log = logging.getLogger(__name__)

_ONLINE_WINDOW_SECONDS = 180


class ClientsScreen(Screen):
    BINDINGS = [
        Binding("a", "add", tr("tui.key.add")),
        Binding("r", "revoke", tr("tui.clients.key_revoke")),
        Binding("t", "rotate", tr("tui.clients.key_rotate")),
        Binding("d", "toggle_enabled", tr("tui.clients.key_toggle")),
        Binding("P", "prune", tr("tui.clients.key_prune")),
        Binding("slash", "focus_search", tr("tui.key.search")),
        Binding("escape", "back", tr("tui.key.back"), priority=True),
        Binding("q", "quit", tr("tui.key.quit"), priority=True),
        Binding("question_mark", "help", tr("tui.key.help")),
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
            yield Input(placeholder=tr("tui.clients.search_ph"), id="search")
            yield DataTable(id="table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns(
            "●", tr("tui.clients.col_name"), tr("tui.clients.col_address"),
            tr("tui.clients.col_status"), tr("tui.clients.col_hs"), "rx", "tx",
            tr("tui.clients.col_endpoint"), tr("tui.clients.col_expires"),
        )
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
            if c.state == "disabled":
                dot, status, hs, rx, tx, endpoint = "⊘", tr("tui.st.disabled"), "—", "—", "—", "—"
            elif peer is None:
                dot, status, hs, rx, tx, endpoint = "○", tr("tui.st.unknown"), "—", "—", "—", "—"
            elif peer.latest_handshake is None:
                dot, status, hs, rx, tx, endpoint = (
                    "○", tr("tui.st.idle"), tr("tui.st.never"), "0 B", "0 B", "—",
                )
            else:
                age = now - peer.latest_handshake
                if age < _ONLINE_WINDOW_SECONDS:
                    dot, status = "●", f"[{OK}]{tr('tui.st.online')}[/]"
                else:
                    dot, status = "◐", f"[{WARN}]{tr('tui.st.offline')}[/]"
                hs = _fmt_age(age)
                rx = _fmt_bytes(peer.transfer_rx)
                tx = _fmt_bytes(peer.transfer_tx)
                endpoint = peer.endpoint or "—"
            expires = c.expires_at or "—"
            table.add_row(dot, c.name, c.address, status, hs, rx, tx, endpoint, expires)

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
            self.notify(tr("tui.clients.select_first"), severity="warning")
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
                self.notify(tr("tui.clients.not_found", name=name), severity="error")
                return
            # Refresh in-memory config from disk so subsequent refreshes are correct.
            self.app.reload_config()
            self.refresh_table()

        self.app.push_screen(
            ConfirmModal(
                title=tr("tui.clients.revoke_title", name=name),
                body=tr("tui.clients.revoke_body"),
                ok_label=tr("tui.clients.key_revoke"),
            ),
            _go,
        )

    def action_toggle_enabled(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify(tr("tui.clients.select_first"), severity="warning")
            return
        entry = next((c for c in self.app.config.clients if c.name == name), None)
        if entry is None:
            self.notify(tr("tui.clients.not_found", name=name), severity="error")
            return
        enable = entry.state == "disabled"
        from outwarp_server import operations
        try:
            operations.set_client_enabled(
                self.app.config, name, enable, config_path=self.app.config_path,
            )
        except KeyError:
            self.notify(tr("tui.clients.not_found", name=name), severity="error")
            return
        self.app.reload_config()
        self.refresh_table()
        self.notify(
            tr("tui.clients.enabled", name=name) if enable
            else tr("tui.clients.disabled", name=name),
            severity="information",
        )

    def action_rotate(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify(tr("tui.clients.select_first"), severity="warning")
            return

        from outwarp_server.tui.modals.confirm import ConfirmModal

        def _go(result: bool | None) -> None:
            if not result:
                return
            from outwarp_server import operations
            try:
                res = operations.rotate_client(
                    self.app.config, name,
                    config_path=self.app.config_path,
                    output_dir=self.app.config_path.parent,
                )
            except (ValueError, KeyError) as exc:
                self.notify(str(exc), severity="error")
                return
            self.app.reload_config()
            self.refresh_table()
            self.notify(
                tr("tui.clients.rotated", name=name, file=res.owcfg_path.name),
                severity="information",
            )
            from outwarp_server.tui.modals.qr import QrModal
            self.app.push_screen(QrModal(res.owcfg_path))

        self.app.push_screen(
            ConfirmModal(
                title=tr("tui.clients.rotate_title", name=name),
                body=tr("tui.clients.rotate_body"),
                ok_label=tr("tui.clients.key_rotate"),
            ),
            _go,
        )

    def action_prune(self) -> None:
        import time

        from outwarp_server.tui.modals.confirm import ConfirmModal

        now = time.strftime("%Y-%m-%d")
        expired = [
            c.name for c in self.app.config.clients
            if c.expires_at and c.expires_at < now
        ]
        if not expired:
            self.notify(tr("tui.clients.none_expired"), severity="information")
            return

        def _go(result: bool | None) -> None:
            if not result:
                return
            from outwarp_server import operations
            for name in expired:
                try:
                    operations.revoke_client(
                        self.app.config, name, config_path=self.app.config_path,
                    )
                    self.app.reload_config()
                except (KeyError, Exception) as exc:
                    self.notify(
                        tr("tui.clients.revoke_error", name=name, error=exc), severity="error",
                    )
            self.refresh_table()
            self.notify(tr("tui.clients.pruned", n=len(expired)), severity="information")

        self.app.push_screen(
            ConfirmModal(
                title=tr("tui.clients.prune_title", n=len(expired)),
                body=", ".join(expired),
                ok_label=tr("tui.clients.prune_ok"),
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
        return tr("tui.ago_s", n=seconds)
    if seconds < 3600:
        return tr("tui.ago_m", n=seconds // 60)
    if seconds < 86400:
        return tr("tui.ago_h", n=seconds // 3600)
    return tr("tui.ago_d", n=seconds // 86400)
