"""Settings modal for the OutWarp TUI.

Shares the on-disk ``settings.json`` with the pywebview GUI - a toggle here is
visible on next launch of either UI. Only exposes the toggles that make sense
for the headless/TUI experience: GUI-only options like ``minimize_to_tray`` or
``start_at_boot`` stay where the GUI's tray menu can wire them.

Live application: when the tunnel is already running, flipping
``allow_tls_intercept`` / ``auto_reconnect`` propagates to the active
``TunnelManager`` via its setters. That way the user doesn't have to
disconnect-reconnect to re-handshake against an inspection proxy.
"""

from __future__ import annotations

import logging

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
        "Bring the tunnel up automatically when 'outwarp-cli tui' starts.",
    ),
]


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
        # Switch IDs follow `switch-<settings-key>` so we can recover the key
        # without a separate lookup table.
        sid = event.switch.id or ""
        if not sid.startswith("switch-"):
            return
        key = sid.removeprefix("switch-")
        new_value = bool(event.value)
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

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_edit_profile(self) -> None:
        # Close the modal first so the editor screen owns the layout — pushing
        # a Screen on top of a ModalScreen leaves the modal's dim overlay
        # rendered behind the inputs, which looks broken.
        self.dismiss(None)
        self.app.push_screen("profile")
