from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Select, Static

from outwarp_server.i18n import LANG_NAMES, LANGS
from outwarp_server.i18n import t as tr
from outwarp_server.tui.tokens import DIM, OK


class SettingsModal(ModalScreen[None]):
    """The settings the GUI and the panel share that make sense in a terminal."""

    BINDINGS = [
        ("escape", "dismiss", tr("tui.key.back")),
        ("q", "dismiss", tr("tui.key.back")),
    ]

    def __init__(self) -> None:
        super().__init__()
        from outwarp_server.api import _load_settings

        self._settings = _load_settings()

    def compose(self) -> ComposeResult:
        with Container(id="settings-modal"):
            yield Static(f"[bold]{tr('tui.key.settings')}[/bold]")
            yield Static(f"[b]{tr('tui.set.language')}[/b]")
            yield Static(f"[{DIM}]{tr('tui.set.language_hint')}[/]")
            yield Select(
                [(tr("tui.set.language_auto"), "auto"),
                 *((LANG_NAMES.get(code, code), code) for code in LANGS)],
                value=self._current_language(),
                allow_blank=False,
                id="select-language",
            )
            yield Static("", id="settings-status")

    def _current_language(self) -> str:
        # A value the picker has no option for (hand edit, a newer build's
        # language) would make Select raise; the rest of the app reads it as auto.
        lang = self._settings.get("language", "auto")
        return lang if lang in LANGS else "auto"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "select-language" or not isinstance(event.value, str):
            return
        if self._current_language() == event.value:
            return
        from outwarp_server.api import _save_settings

        self._settings["language"] = event.value
        _save_settings(self._settings)
        self.query_one("#settings-status", Static).update(
            f"[{OK}]✓[/] {tr('tui.set.language_saved')}"
        )

    def action_dismiss(self) -> None:
        self.dismiss()
