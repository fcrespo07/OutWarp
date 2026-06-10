from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

_LINES = [
    "[bold]Global[/bold]",
    "  q      Quit",
    "  s      Settings (TLS-intercept, auto-reconnect, auto-connect)",
    "  ?      Help",
    "  Esc    Back / cancel",
    "",
    "[bold]Dashboard[/bold]",
    "  k      Disconnect",
    "  r      Reconnect",
    "  l      Logs (fullscreen)",
    "  p      Edit profile",
    "  c      Copy server endpoint to clipboard",
    "",
    "[bold]Connecting[/bold]",
    "  k      Cancel",
    "",
    "[bold]Empty state[/bold]",
    "  i      Import .owcfg",
    "",
    "[bold]Logs screen[/bold]",
    "  /      Search / filter",
    "  e      Toggle errors-only filter",
    "  w      Toggle warnings+ filter",
    "  p      Pause / resume live tail",
    "  g      Jump to top",
    "  G      Jump to bottom",
    "",
    "[bold]Linux service (Settings)[/bold]",
    "  Background service  Toggle the user-level systemd daemon",
    "  Start before login  Toggle loginctl linger (auto-start)",
    "",
    "[bold]Doctor[/bold]",
    "  r      Re-run all checks",
    "  f      Apply auto-fixable check",
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
