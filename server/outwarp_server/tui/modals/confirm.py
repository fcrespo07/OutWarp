from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("y", "ok", "Confirm"),
        ("enter", "ok", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, title: str, body: str, ok_label: str = "OK") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Container(id="add-modal"):
            yield Static(f"[bold]{self._title}[/]")
            yield Static(self._body)
            yield Static(
                f"[#6e747e]Press [b]y[/b] to {self._ok_label.lower()}, "
                f"[b]n[/b] or [b]Esc[/b] to cancel.[/]"
            )

    def action_ok(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
