"""Switch between, or remove, imported profiles. One tunnel at a time."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

from outwarp import profiles
from outwarp.config import ClientConfig, ConfigError
from outwarp.i18n import pad
from outwarp.i18n import t as tr
from outwarp.tui.tokens import DIM, OK


def _label(ref: profiles.ProfileRef, active: bool) -> str:
    try:
        cfg = ClientConfig.load(ref.path)
        name = cfg.name or ref.id
        where = f"{cfg.server.endpoint}:{cfg.server.port}"
    except ConfigError:
        name, where = ref.id, "?"
    mark = f"[{OK}]●[/]" if active else "○"
    tag = f"  [{OK}]{tr('tui.profiles.active')}[/]" if active else ""
    return f"{mark} {pad(name, 22)} [{DIM}]{where}[/]{tag}"


class ProfilesModal(ModalScreen[None]):
    BINDINGS = [
        ("enter", "use", tr("tui.profiles.key_use")),
        ("x", "remove", tr("tui.profiles.key_remove")),
        ("i", "import", tr("tui.empty.key_import")),
        ("escape", "dismiss", tr("tui.key.close")),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="profiles-modal"):
            yield Static(f"[bold]{tr('tui.profiles.title')}[/bold]")
            yield ListView(id="profile-list")
            yield Static("", id="profiles-status")
            yield Static(f"[{DIM}]{tr('tui.profiles.keys')}[/]")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self._refs = profiles.list_profiles()
        active = profiles.active_id()
        view = self.query_one("#profile-list", ListView)
        view.clear()
        for ref in self._refs:
            view.append(ListItem(Static(_label(ref, ref.id == active))))
        if not self._refs:
            view.append(ListItem(Static(f"[{DIM}]{tr('tui.empty.none')}[/]")))
        view.focus()

    def _selected(self) -> profiles.ProfileRef | None:
        index = self.query_one("#profile-list", ListView).index
        if index is None or not (0 <= index < len(self._refs)):
            return None
        return self._refs[index]

    def on_list_view_selected(self, _event: ListView.Selected) -> None:
        self.action_use()

    def action_use(self) -> None:
        ref = self._selected()
        if ref is None:
            return
        if ref.id == profiles.active_id():
            self.dismiss(None)
            return
        if getattr(self.app, "service_managed", False):
            self._status(tr("tui.profiles.service"))
            return
        self.app.switch_profile(ref.id)
        self.dismiss(None)

    def action_remove(self) -> None:
        ref = self._selected()
        if ref is None:
            return
        if getattr(self.app, "service_managed", False):
            self._status(tr("tui.profiles.service"))
            return
        from outwarp.tui.modals.confirm import ConfirmModal

        def _go(ok: bool | None) -> None:
            if ok:
                self.app.remove_profile(ref.id)
                self._refresh()

        self.app.push_screen(
            ConfirmModal(
                tr("tui.profiles.remove_title", name=ref.id),
                tr("tui.profiles.remove_body"),
                ok_label=tr("tui.profiles.key_remove"),
            ),
            _go,
        )

    def action_import(self) -> None:
        from outwarp.tui.modals.import_owcfg import ImportModal

        def _done(imported: bool | None) -> None:
            if imported:
                self.app.reload_config()
                self.dismiss(None)

        self.app.push_screen(ImportModal(), _done)

    def _status(self, text: str) -> None:
        self.query_one("#profiles-status", Static).update(text)
