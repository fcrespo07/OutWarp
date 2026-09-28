from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from outwarp_server.i18n import t as tr
from outwarp_server.tui.tokens import DIM


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("y", "ok", tr("tui.confirm.ok")),
        ("enter", "ok", tr("tui.confirm.ok")),
        ("n", "cancel", tr("tui.key.cancel")),
        ("escape", "cancel", tr("tui.key.cancel")),
    ]

    def __init__(self, *, title: str, body: str, ok_label: str = "OK") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Container(id="confirm-modal"):
            yield Static(f"[bold]{self._title}[/]")
            yield Static(self._body)
            yield Static(
                f"[{DIM}]{tr('tui.confirm.keys', action=self._ok_label.lower())}[/]"
            )

    def action_ok(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
