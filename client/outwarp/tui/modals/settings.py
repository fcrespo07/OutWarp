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
from textual.widgets import Static, Switch

from outwarp.settings import load_settings, save_settings
from outwarp.tui.tokens import BAD, OK

log = logging.getLogger(__name__)


# (key, label, hint) for each toggle exposed in this modal. Order = display
# order. Update the help modal if you add or remove rows here.
_TOGGLES: list[tuple[str, str, str]] = [
    (
        "allow_tls_intercept",
        "Allow TLS-intercepting networks",
        "Tolerate a certificate-fingerprint mismatch (corporate/school proxies)."
        " WireGuard's own crypto still protects the traffic.",
    ),
    (
        "auto_reconnect",
        "Auto-reconnect on drop",
        "Replay the reconnect schedule when the tunnel goes down unexpectedly.",
    ),
    (
        "auto_connect",
        "Auto-connect at launch",
        "Bring the tunnel up automatically when 'outwarp tui' starts.",
    ),
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
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
        ("p", "edit_profile", "Edit profile"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        import shutil

        from outwarp.service import is_linger_enabled

        with Container(id="settings-modal"):
            yield Static("[bold]Settings[/bold]")
            yield Static(
                "[dim]Toggles persist to settings.json and are shared with the GUI.[/]"
            )
            for key, label, hint in _TOGGLES:
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=bool(self._settings.get(key, False)),
                        id=f"switch-{key}",
                    )
                    with Container(classes="settings-text"):
                        yield Static(f"[b]{label}[/b]")
                        yield Static(f"[dim]{hint}[/]")

            # Linux-only: background service + linger management
            if sys.platform == "linux" and shutil.which("systemctl") is not None:
                from outwarp.service import service_supported

                supported, why = service_supported()
                yield Static(
                    "\n[b]Background service (Linux)[/b]",
                    classes="settings-section-header",
                )
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=_is_service_enabled(), id=f"switch-{_KEY_SVC}",
                        disabled=not supported,
                    )
                    with Container(classes="settings-text"):
                        yield Static("[b]Run as background daemon[/b]")
                        yield Static(
                            "[dim]Hand the tunnel to a systemd --user unit that keeps it up "
                            "without this TUI (which then just shows its status). "
                            "Equivalent to [bold]outwarp service install[/bold].[/]"
                            + (f"\n[{BAD}]{why}[/]" if not supported else "")
                        )
                with Horizontal(classes="settings-row"):
                    yield Switch(
                        value=is_linger_enabled(), id=f"switch-{_KEY_LINGER}",
                    )
                    with Container(classes="settings-text"):
                        yield Static("[b]Start before login[/b]")
                        yield Static(
                            "[dim]Enable systemd linger so the daemon starts at boot "
                            "before the first login (requires root or sudo NOPASSWD).[/]"
                        )

            if sys.platform == "linux":
                from outwarp.ui_choice import INSTALL_HINT, gui_available

                gui_ok, gui_why = gui_available()
                yield Static("\n[b]Interface (Linux)[/b]", classes="settings-section-header")
                if gui_ok:
                    with Horizontal(classes="settings-row"):
                        yield Switch(
                            value=self._settings.get("preferred_ui") != "tui",
                            id=f"switch-{_KEY_PREFER_GUI}",
                        )
                        with Container(classes="settings-text"):
                            yield Static("[b]Open the graphical window from the app menu[/b]")
                            yield Static(
                                "[dim]On: the launcher opens the tray + window "
                                f"({gui_why}). Off: it opens this terminal UI. "
                                "Same as [bold]outwarp ui gui[/bold] / "
                                "[bold]outwarp ui tui[/bold].[/]"
                            )
                else:
                    yield Static(
                        f"[dim]Graphical window not installed ({gui_why}).\n"
                        f"Add it with [bold]{INSTALL_HINT}[/bold]; this terminal UI "
                        "stays available either way.[/]",
                        classes="settings-row",
                    )

            # Connection-config editing lives on its own screen (room for the
            # 7 editable fields + validation feedback). The modal just exposes
            # the entry point so users discover it from the same surface where
            # they tweak preferences.
            yield Static(
                "[b]Connection profile[/b]\n"
                "[dim]Edit name, MTU, DNS, address, bypass routes and reconnect schedule.[/]\n"
                "[dim]Press [b]p[/b] to open the editor.[/]",
                classes="settings-profile-link",
            )
            yield Static("", id="settings-status")
            yield Static(
                "[dim]Press [b]Esc[/b] / [b]q[/b] to close. Changes save instantly.[/]"
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
                    f"[{BAD}]Could not save: {exc}[/]"
                )
                return
            self.query_one("#settings-status", Static).update(
                f"[{OK}]✓[/] launcher opens the {'GUI' if new_value else 'TUI'}"
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
                f"[{BAD}]Could not save: {exc}[/]"
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
        self.query_one("#settings-status", Static).update(
            f"[{OK}]✓[/] {key.replace('_', ' ')} = {new_value}"
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
        status.update("[dim]Applying service change…[/]")
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
                        msg = (f"[{OK}]Service enabled — the tunnel now runs in the background; "
                               "this TUI shows its status.[/]")
                        app.call_from_thread(app.enter_viewer_mode)
                    else:
                        msg = f"[{BAD}]{_last() or f'service install failed (rc={rc})'}[/]"
                        app.call_from_thread(app.leave_viewer_mode)
                else:
                    rc = uninstall_service(echo=lines.append)
                    if rc == 0:
                        msg = f"[{OK}]Service disabled — this TUI runs the tunnel again.[/]"
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
        status.update("[dim]Applying linger change…[/]")

        def _run() -> None:
            ok_flag, hint = set_linger(enable)
            if ok_flag:
                msg = (
                    f"[{OK}]Linger {'enabled' if enable else 'disabled'}. "
                    f"{'Daemon will now start at boot.' if enable else ''}[/]"
                )
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
