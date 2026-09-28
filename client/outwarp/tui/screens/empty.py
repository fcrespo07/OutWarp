from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from outwarp.i18n import t as tr


class EmptyScreen(Screen):
    """First-run state: no .owcfg imported yet."""

    BINDINGS = [
        ("i", "import", tr("tui.empty.key_import")),
        ("q", "quit", tr("tui.key.quit")),
        ("question_mark", "help", tr("tui.key.help")),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static("[bold]OutWarp[/bold]")
            yield Static(tr("tui.empty.none"))
            yield Static(tr("tui.empty.hint"))
        yield Footer()

    def action_import(self) -> None:
        from outwarp.tui.modals.import_owcfg import ImportModal
        self.app.push_screen(ImportModal(), self._on_imported)

    def action_help(self) -> None:
        from outwarp.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())

    def _on_imported(self, imported: bool | None) -> None:
        if imported:
            # The app's on_state listener will route to Connecting/Dashboard.
            self.app.reload_config()
