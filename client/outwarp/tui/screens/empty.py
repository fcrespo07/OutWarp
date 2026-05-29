from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class EmptyScreen(Screen):
    """First-run state: no .owcfg imported yet."""

    BINDINGS = [
        ("i", "import", "Import .owcfg"),
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static("[bold]OutWarp[/bold]")
            yield Static("No profile imported yet.")
            yield Static("Press [b]i[/b] to import a .owcfg file, or [b]q[/b] to quit.")
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
