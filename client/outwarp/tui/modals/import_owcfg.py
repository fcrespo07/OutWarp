from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, ListView, ListItem, Static

from outwarp.config import ConfigError, import_owcfg
from outwarp.tui.tokens import BAD, DIM


def _scan_owcfg() -> list[Path]:
    """Return .owcfg files found in common locations, newest-first."""
    candidates: list[Path] = []
    home = Path.home()
    for folder in (home / "Downloads", home / "Desktop", home):
        try:
            candidates.extend(folder.glob("*.owcfg"))
        except OSError:
            pass
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in candidates:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    unique.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return unique[:8]


class ImportModal(ModalScreen[bool]):
    """Prompts for a .owcfg file — shows a scan list if files are found."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Import"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._found: list[Path] = _scan_owcfg()

    def compose(self) -> ComposeResult:
        with Container(id="import-modal"):
            yield Static("[bold]Import profile[/bold]")
            if self._found:
                yield Static("Select a file or type a path below:")
                items = [ListItem(Static(str(p)), id=f"item-{i}") for i, p in enumerate(self._found)]
                yield ListView(*items, id="file-list")
            else:
                yield Static("Type the absolute path to a .owcfg file:")
            yield Input(
                placeholder=str(Path.home() / "Downloads" / "your-name.owcfg"),
                id="path",
            )
            yield Static("", id="result")
            yield Static(
                f"[{DIM}]Enter to import, Esc to cancel.[/]",
            )

    def on_mount(self) -> None:
        if self._found:
            self.query_one("#file-list", ListView).focus()
        else:
            self.query_one("#path", Input).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self._list_item_index(event.item)
        if idx is not None and idx < len(self._found):
            self._do_import(self._found[idx])

    def _list_item_index(self, item: ListItem) -> int | None:
        if item.id and item.id.startswith("item-"):
            try:
                return int(item.id[5:])
            except ValueError:
                pass
        return None

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_submit(self) -> None:
        raw = self.query_one("#path", Input).value.strip()
        if not raw:
            # If a list item is highlighted and user pressed Enter with empty input,
            # defer to the list selection.
            try:
                lv = self.query_one("#file-list", ListView)
                if lv.index is not None and lv.index < len(self._found):
                    self._do_import(self._found[lv.index])
                    return
            except Exception:
                pass
            self.query_one("#result", Static).update(f"[{BAD}]Path is required.[/]")
            return
        path = Path(raw).expanduser()
        if not path.exists():
            self.query_one("#result", Static).update(
                f"[{BAD}]File not found: {path}[/]"
            )
            return
        self._do_import(path)

    def _do_import(self, path: Path) -> None:
        try:
            import_owcfg(path)
        except ConfigError as exc:
            self.query_one("#result", Static).update(f"[{BAD}]Invalid .owcfg: {exc}[/]")
            return
        self.dismiss(True)
