from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

_LINES = [
    "[bold]Global[/bold]",
    "  q      Quit",
    "  ?      Help",
    "  Esc    Back / cancel",
    "",
    "[bold]Dashboard[/bold]",
    "  k      Disconnect",
    "  r      Reconnect",
    "  l      Logs (fullscreen)",
    "",
    "[bold]Empty state[/bold]",
    "  i      Import .owcfg",
]


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("q", "dismiss", "Back"),
        ("question_mark", "dismiss", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-modal"):
            yield Static("[bold]OutWarp · client[/bold]")
            for line in _LINES:
                yield Static(line)

    def action_dismiss(self) -> None:
        self.dismiss()
