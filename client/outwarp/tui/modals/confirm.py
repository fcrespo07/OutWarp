from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, body: str, ok_label: str = "OK") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Container(id="confirm-modal"):
            yield Static(f"[bold]{self._title}[/bold]")
            yield Static(self._body)
            with Horizontal(id="confirm-buttons"):
                yield Button(self._ok_label, id="ok", variant="error")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)
