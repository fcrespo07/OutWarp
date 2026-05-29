from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from outwarp.config import ConfigError, import_owcfg


class ImportModal(ModalScreen[bool]):
    """Prompts for a path to a .owcfg file and imports it."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Import"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="import-modal"):
            yield Static("[bold]Import profile[/bold]")
            yield Static("Type the absolute path to a .owcfg file:")
            yield Input(
                placeholder=str(Path.home() / "Downloads" / "your-name.owcfg"),
                id="path",
            )
            yield Static("", id="result")
            yield Static(
                "[dim]Press [b]Enter[/b] to import, [b]Esc[/b] to cancel.[/]",
            )

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_submit(self) -> None:
        raw = self.query_one("#path", Input).value.strip()
        if not raw:
            self.query_one("#result", Static).update("[#ff5c7a]Path is required.[/]")
            return
        path = Path(raw).expanduser()
        if not path.exists():
            self.query_one("#result", Static).update(
                f"[#ff5c7a]File not found: {path}[/]"
            )
            return
        try:
            import_owcfg(path)
        except ConfigError as exc:
            self.query_one("#result", Static).update(f"[#ff5c7a]Invalid .owcfg: {exc}[/]")
            return
        self.dismiss(True)
