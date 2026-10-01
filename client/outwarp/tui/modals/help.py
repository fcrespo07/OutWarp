from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from outwarp.i18n import t as tr

# (heading key, [(keys, description key), ...]) — rendered in the UI language.
_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("tui.help.global", [
        ("q", "tui.key.quit"),
        ("s", "tui.help.settings"),
        ("P", "tui.help.profiles"),
        ("?", "tui.key.help"),
        ("Esc", "tui.help.back"),
    ]),
    ("tui.help.dashboard", [
        ("k", "tui.help.disconnect"),
        ("r", "tui.help.reconnect"),
        ("l", "tui.help.logs"),
        ("p", "tui.help.edit_profile"),
        ("c", "tui.help.copy_endpoint"),
    ]),
    ("tui.help.connecting", [("k", "tui.key.cancel")]),
    ("tui.help.empty", [("i", "tui.empty.key_import")]),
    ("tui.help.logs_screen", [
        ("/", "tui.help.search"),
        ("e", "tui.help.errors"),
        ("w", "tui.help.warnings"),
        ("p", "tui.help.pause"),
        ("x", "tui.help.export"),
        ("c", "tui.help.clear_view"),
        ("g", "tui.help.top"),
        ("G", "tui.help.bottom"),
    ]),
    ("tui.help.service", [
        ("", "tui.help.service_daemon"),
        ("", "tui.help.service_linger"),
    ]),
    ("tui.help.doctor", [
        ("r", "tui.help.rerun"),
        ("f", "tui.help.fix"),
    ]),
]


def _lines() -> list[str]:
    lines: list[str] = []
    for heading, rows in _SECTIONS:
        if lines:
            lines.append("")
        lines.append(f"[bold]{tr(heading)}[/bold]")
        lines.extend(f"  {keys:<6} {tr(desc)}" if keys else f"  {tr(desc)}" for keys, desc in rows)
    return lines


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", tr("tui.key.back")),
        ("q", "dismiss", tr("tui.key.back")),
        ("question_mark", "dismiss", tr("tui.key.back")),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-modal"):
            yield Static("[bold]OutWarp · client[/bold]")
            for line in _lines():
                yield Static(line)

    def action_dismiss(self) -> None:
        self.dismiss()
