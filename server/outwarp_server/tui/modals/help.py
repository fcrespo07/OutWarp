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
    "  c      Clients screen",
    "  a      Add client",
    "  d      Doctor",
    "  l      Logs",
    "  r      Restart services",
    "",
    "[bold]Clients[/bold]",
    "  /      Search",
    "  a      Add",
    "  r      Revoke selected",
    "",
    "[bold]Doctor[/bold]",
    "  F      Apply auto-fix",
    "  r      Re-run checks",
]


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("q", "dismiss", "Back"),
        ("question_mark", "dismiss", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-modal"):
            yield Static("[bold]OutWarp · server[/bold]")
            for line in _LINES:
                yield Static(line)

    def action_dismiss(self) -> None:
        self.dismiss()
