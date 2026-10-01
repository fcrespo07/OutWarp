"""Settings modal for the OutWarp TUI.

Shares the on-disk ``settings.json`` with the pywebview GUI - a toggle here is
visible on next launch of either UI. Only exposes the toggles that make sense
for the headless/TUI experience: GUI-only options like ``minimize_to_tray`` or
``start_at_boot`` stay where the GUI's tray menu can wire them.

Live application: when the tunnel is already running, flipping
``allow_tls_intercept`` / ``auto_reconnect`` propagates to the active
``TunnelManager`` via its setters. That way the user doesn't have to
disconnect-reconnect to re-handshake against an inspection proxy.

On Linux, the modal also exposes the systemd user-service toggle and the
``loginctl`` linger toggle so the TUI can serve as the single control surface
for background-service management.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import threading

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Select, Static, Switch

from outwarp.i18n import LANG_NAMES, LANGS
from outwarp.i18n import t as tr
from outwarp.settings import load_settings, save_settings
from outwarp.tui.tokens import BAD, OK

log = logging.getLogger(__name__)


# (key, label i18n key, hint i18n key) for each toggle exposed in this modal. Order = display
# order. Update the help modal if you add or remove rows here.
_TOGGLES: list[tuple[str, str, str]] = [
    ("allow_tls_intercept", "tui.set.tls", "tui.set.tls_hint"),
    ("auto_reconnect", "tui.set.reconnect", "tui.set.reconnect_hint"),
    ("auto_connect", "tui.set.autoconnect", "tui.set.autoconnect_hint"),
    ("kill_switch", "tui.set.killswitch", "tui.set.killswitch_hint"),
]

# Pseudo-keys for Linux system-level toggles that don't map to settings.json.
# Prefixed with "_" so the generic settings handler recognises them as special.
_KEY_SVC = "_svc_enabled"
_KEY_LINGER = "_linger_enabled"
_KEY_PREFER_GUI = "_prefer_gui"


def _is_service_enabled() -> bool:
    """Check whether the outwarp systemd user unit is enabled."""
    import shutil
    if sys.platform != "linux" or shutil.which("systemctl") is None:
        return False
    r = subprocess.run(
        ["systemctl", "--user", "is-enabled", "outwarp-client.service"],
        capture_output=True, text=True, check=False,
    )
    return r.returncode == 0


class SettingsModal(ModalScreen[None]):
    """Toggle-board for client preferences. Persists to ``settings.json``."""

    BINDINGS = [
        ("escape", "dismiss", tr("tui.key.close")),
        ("q", "dismiss", tr("tui.key.close")),
        ("p", "edit_profile", tr("tui.help.edit_profile")),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        import shutil

        from outwarp.service import is_linger_enabled

        with Container(id="settings-modal"):
            yield Static(f"[bold]{tr('tui.key.settings')}[/bold]")
            yield Static(f"[dim]{tr('tui.set.persist')}[/]")
            with Container(classes="settings-text settings-row"):
                yield Static(f"[b]{tr('tui.set.language')}[/b]")
                yield Static(f"[dim]{tr('tui.set.language_hint')}[/]")
                yield Select(
                    [(tr("tui.set.language_auto"), "auto"),
                     *((LANG_NAMES.get(code, code), code) for code in LANGS)],
                    value=self._settings.get("language", "auto"),
                    allow_blank=False,
                    id="select-language",
                )
            for key, label, hint in _TOGGLES:
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=bool(self._settings.get(key, False)),
                        id=f"switch-{key}",
                    )
                    with Container(classes="settings-text"):
                        yield Static(f"[b]{tr(label)}[/b]")
                        yield Static(f"[dim]{tr(hint)}[/]")

            # Linux-only: background service + linger management
            if sys.platform == "linux" and shutil.which("systemctl") is not None:
                from outwarp.service import service_supported

                supported, why = service_supported()
                yield Static(
                    f"\n[b]{tr('tui.set.service_header')}[/b]",
                    classes="settings-section-header",
                )
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=_is_service_enabled(), id=f"switch-{_KEY_SVC}",
                        disabled=not supported,
                    )
                    with Container(classes="settings-text"):
                        yield Static(f"[b]{tr('tui.set.daemon')}[/b]")
                        yield Static(
                            f"[dim]{tr('tui.set.daemon_hint')}[/]"
                            + (f"\n[{BAD}]{why}[/]" if not supported else "")
                        )
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=is_linger_enabled(), id=f"switch-{_KEY_LINGER}",
                    )
                    with Container(classes="settings-text"):
                        yield Static(f"[b]{tr('tui.set.linger')}[/b]")
                        yield Static(f"[dim]{tr('tui.set.linger_hint')}[/]")

            if sys.platform == "linux":
                from outwarp.ui_choice import INSTALL_HINT, gui_available

                gui_ok, gui_why = gui_available()
                yield Static(
                    f"\n[b]{tr('tui.set.ui_header')}[/b]", classes="settings-section-header"
                )
                if gui_ok:
                    with Horizontal(classes="settings-row"):
                        yield Switch(
                            value=self._settings.get("preferred_ui") != "tui",
                            id=f"switch-{_KEY_PREFER_GUI}",
                        )
                        with Container(classes="settings-text"):
                            yield Static(f"[b]{tr('tui.set.prefer_gui')}[/b]")
                            yield Static(f"[dim]{tr('tui.set.prefer_gui_hint', why=gui_why)}[/]")
                else:
                    yield Static(
                        f"[dim]{tr('tui.set.no_gui', why=gui_why, hint=INSTALL_HINT)}[/]",
                        classes="settings-row",
                    )

            # Connection-config editing lives on its own screen (room for the
            # 7 editable fields + validation feedback). The modal just exposes
            # the entry point so users discover it from the same surface where
            # they tweak preferences.
            yield Static(
                f"[b]{tr('tui.set.profile')}[/b]\n"
                f"[dim]{tr('tui.set.profile_hint')}[/]\n"
                f"[dim]{tr('tui.set.profile_open')}[/]",
                classes="settings-profile-link",
            )
            yield Static("", id="settings-status")
            yield Static(
                f"[dim]{tr('tui.set.close_hint')}[/]"
            )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "select-language" or not isinstance(event.value, str):
            return
        if self._settings.get("language", "auto") == event.value:
            return
        self._settings["language"] = event.value
        try:
            save_settings(self._settings)
        except OSError as exc:
            log.exception("Could not save settings.json")
            self.query_one("#settings-status", Static).update(
                f"[{BAD}]{tr('tui.set.save_failed', error=exc)}[/]"
            )
            return
        self.app._settings = dict(self._settings)
        self.query_one("#settings-status", Static).update(
            f"[{OK}]✓[/] {tr('tui.set.language_saved')}"
        )

    def on_switch_changed(self, event: Switch.Changed) -> None:
        sid = event.switch.id or ""
        if not sid.startswith("switch-"):
            return
        key = sid.removeprefix("switch-")
        new_value = bool(event.value)

        # System-level toggles — handled separately, not saved to settings.json
        if key == _KEY_SVC:
            self._toggle_service(new_value)
            return
        if key == _KEY_LINGER:
            self._toggle_linger(new_value)
            return
        if key == _KEY_PREFER_GUI:
            # Switch ON = let the launcher pick the GUI ("auto" keeps the
            # headless/SSH fallback); OFF = always the TUI.
            self._settings["preferred_ui"] = "auto" if new_value else "tui"
            try:
                save_settings(self._settings)
            except OSError as exc:
                log.exception("Could not save settings.json")
                self.query_one("#settings-status", Static).update(
                    f"[{BAD}]{tr('tui.set.save_failed', error=exc)}[/]"
                )
                return
            self.query_one("#settings-status", Static).update(
                f"[{OK}]✓[/] "
                + tr("tui.set.launcher_gui" if new_value else "tui.set.launcher_tui")
            )
            return

        # Standard settings.json path
        if self._settings.get(key) == new_value:
            return
        self._settings[key] = new_value
        try:
            save_settings(self._settings)
        except OSError as exc:
            log.exception("Could not save settings.json")
            self.query_one("#settings-status", Static).update(
                f"[{BAD}]{tr('tui.set.save_failed', error=exc)}[/]"
            )
            return

        # Live-apply to the running TunnelManager so the user doesn't have to
        # restart the TUI / disconnect-reconnect. The setters are no-ops when
        # the manager is None (no profile imported yet).
        mgr = getattr(self.app, "manager", None)
        if mgr is not None:
            if key == "allow_tls_intercept":
                mgr.allow_tls_intercept = new_value
            elif key == "auto_reconnect":
                mgr.auto_reconnect = new_value
            elif key == "kill_switch":
                mgr.kill_switch_enabled = new_value
                if not new_value:
                    # Always release on disable, as the GUI does.
                    with contextlib.suppress(Exception):
                        from outwarp.platforms import get_platform
                        get_platform().release_kill_switch()
        # The dashboard cards read the app's copy.
        self.app._settings = dict(self._settings)
        label = next((tr(row[1]) for row in _TOGGLES if row[0] == key), key)
        self.query_one("#settings-status", Static).update(
            f"[{OK}]✓[/] {label}: {tr('tui.on') if new_value else tr('tui.off')}"
        )

    def _toggle_service(self, enable: bool) -> None:
        """Hand the tunnel over to the systemd user unit, or take it back.

        Enabling used to just run `systemctl --user enable --now` next to
        this TUI's own tunnel: the daemon's `wg-quick up` tore the TUI's
        interface down, the TUI reconnected and tore the daemon's down, and
        the two flapped the link. Now: stop our manager first, install the
        unit, and become a viewer; on failure restart our manager. Disabling
        stops the unit and reloads the config so this process owns the
        tunnel again. Messages come back through `echo` (no stdout capture)
        and the last line is shown in full.
        """
        from outwarp.service import install_service, uninstall_service

        status = self.query_one("#settings-status", Static)
        status.update(f"[dim]{tr('tui.set.applying_service')}[/]")
        app = self.app
        lines: list[str] = []

        def _last() -> str:
            for line in reversed(lines):
                if line.strip():
                    return line.strip()
            return ""

        def _run() -> None:
            try:
                if enable:
                    mgr = getattr(app, "manager", None)
                    if mgr is not None:
                        mgr.stop()
                    if getattr(app, "_owner_lock", None) is not None:
                        app._owner_lock.release()
                        app._owner_lock = None
                    rc = install_service(echo=lines.append)
                    if rc == 0:
                        # XDG autostart of the GUI would make a second owner
                        # at login; the service takes that role now.
                        if self._settings.get("start_at_boot"):
                            self._settings["start_at_boot"] = False
                            with contextlib.suppress(Exception):
                                save_settings(self._settings)
                            with contextlib.suppress(Exception):
                                from outwarp.platforms import get_platform
                                get_platform().uninstall_autostart()
                        msg = f"[{OK}]{tr('tui.set.service_on')}[/]"
                        app.call_from_thread(app.enter_viewer_mode)
                    else:
                        msg = f"[{BAD}]{_last() or f'service install failed (rc={rc})'}[/]"
                        app.call_from_thread(app.leave_viewer_mode)
                else:
                    rc = uninstall_service(echo=lines.append)
                    if rc == 0:
                        msg = f"[{OK}]{tr('tui.set.service_off')}[/]"
                        app.call_from_thread(app.leave_viewer_mode)
                    else:
                        msg = f"[{BAD}]{_last() or f'service uninstall failed (rc={rc})'}[/]"
            except Exception as exc:
                log.exception("toggle_service failed")
                msg = f"[{BAD}]{exc}[/]"
            app.call_from_thread(
                lambda: self.query_one("#settings-status", Static).update(msg)
            )

        threading.Thread(target=_run, daemon=True, name="outwarp-svc-toggle").start()

    def _toggle_linger(self, enable: bool) -> None:
        """Enable or disable systemd user linger in a background thread."""
        from outwarp.service import set_linger

        status = self.query_one("#settings-status", Static)
        status.update(f"[dim]{tr('tui.set.applying_linger')}[/]")

        def _run() -> None:
            ok_flag, hint = set_linger(enable)
            if ok_flag:
                msg = f"[{OK}]{tr('tui.set.linger_on' if enable else 'tui.set.linger_off')}[/]"
            else:
                msg = f"[{BAD}]{hint}[/]"
            self.app.call_from_thread(
                lambda: self.query_one("#settings-status", Static).update(msg)
            )

        threading.Thread(target=_run, daemon=True, name="outwarp-linger-toggle").start()

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_edit_profile(self) -> None:
        # Close the modal first so the editor screen owns the layout — pushing
        # a Screen on top of a ModalScreen leaves the modal's dim overlay
        # rendered behind the inputs, which looks broken.
        self.dismiss(None)
        self.app.push_screen("profile")
