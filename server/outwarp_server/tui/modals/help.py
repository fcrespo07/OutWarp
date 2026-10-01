from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from outwarp_server.i18n import t as tr

# (heading key, [(keys, description key), ...]) — rendered in the UI language.
_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("tui.help.global", [
        ("q", "tui.key.quit"),
        ("?", "tui.key.help"),
        ("Esc", "tui.help.back"),
    ]),
    ("tui.help.dashboard", [
        ("c", "tui.help.clients_screen"),
        ("a", "tui.help.add_client"),
        ("d", "tui.key.doctor"),
        ("l", "tui.key.logs"),
        ("r", "tui.help.restart"),
        ("p", "tui.help.probe"),
        ("s", "tui.help.settings"),
    ]),
    ("tui.help.clients", [
        ("/", "tui.key.search"),
        ("a", "tui.key.add"),
        ("r", "tui.help.revoke"),
        ("d", "tui.help.toggle"),
    ]),
    ("tui.key.doctor", [
        ("F", "tui.help.fix"),
        ("r", "tui.help.rerun"),
    ]),
]


def _lines() -> list[str]:
    lines: list[str] = []
    for heading, rows in _SECTIONS:
        if lines:
            lines.append("")
        lines.append(f"[bold]{tr(heading)}[/bold]")
        lines.extend(f"  {keys:<6} {tr(desc)}" for keys, desc in rows)
    return lines


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", tr("tui.key.back")),
        ("q", "dismiss", tr("tui.key.back")),
        ("question_mark", "dismiss", tr("tui.key.back")),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-modal"):
            yield Static("[bold]OutWarp · server[/bold]")
            for line in _lines():
                yield Static(line)

    def action_dismiss(self) -> None:
        self.dismiss()
