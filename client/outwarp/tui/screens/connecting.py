from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

PHASE_LABELS: list[tuple[str, str]] = [
    ("resolve", "dns + tcp connect"),
    ("tls",     "tls handshake"),
    ("wg",      "wireguard interface up"),
    ("ws",      "wstunnel websocket upgrade"),
]
PHASE_ORDER = [k for k, _ in PHASE_LABELS]

_GLYPH = {"done": "●", "active": "◐", "pending": "○"}


class PhaseRow(Static):
    state = reactive("pending")

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def watch_state(self, value: str) -> None:
        self.set_class(value == "done", "done")
        self.set_class(value == "active", "active")
        self.set_class(value == "pending", "pending")
        self.update(self._build_label())

    def _build_label(self) -> str:
        icon = _GLYPH.get(self.state, "○")
        return f"  {icon}  {self._label}"

    def on_mount(self) -> None:
        self.update(self._build_label())


class ConnectingScreen(Screen):
    """Live stepper that mirrors `TunnelManager.phase`."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
        ("k", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static("[bold]Connecting...[/bold]", id="connect-title")
            self._rows: list[PhaseRow] = []
            for key, label in PHASE_LABELS:
                row = PhaseRow(label)
                row.id = f"phase-{key}"
                self._rows.append(row)
                yield row
            yield Static("", id="attempt")
            yield Static("", id="error")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.25, self.refresh_phases)
        self.refresh_phases()

    def refresh_phases(self) -> None:
        mgr = getattr(self.app, "manager", None)
        if mgr is None:
            return
        current = mgr.phase or ""
        idx = PHASE_ORDER.index(current) if current in PHASE_ORDER else len(PHASE_ORDER)
        if current == "done":
            idx = len(PHASE_ORDER)
        for i, row in enumerate(self._rows):
            if i < idx:
                row.state = "done"
            elif i == idx and current != "done":
                row.state = "active"
            else:
                row.state = "pending"
        attempt = getattr(mgr, "attempt", 0)
        if attempt:
            self.query_one("#attempt", Static).update(f"attempt {attempt}")
        else:
            self.query_one("#attempt", Static).update("")
        err = getattr(mgr, "last_error", None)
        self.query_one("#error", Static).update(
            f"[#ff5c7a]{err}[/]" if err else ""
        )

    def action_cancel(self) -> None:
        mgr = getattr(self.app, "manager", None)
        if mgr is not None:
            mgr.stop()
        self.app.exit(0)

    def action_help(self) -> None:
        from outwarp.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())
