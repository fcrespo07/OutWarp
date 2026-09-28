"""Profile editor screen for the OutWarp client TUI.

Mirrors the per-profile editor that lives in the pywebview GUI (api.update_profile /
api.reset_profile): same editable fields, same validation via
``outwarp.config.apply_profile_patch``, same persistence (config.json plus a
config.original.json snapshot taken on first edit so 'reset' always has a
baseline to restore).

The screen runs *inside* the TUI app, so saving a change immediately rebuilds
the TunnelManager via ``app.start_manager()`` — no manual reconnect needed.
"""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from outwarp.config import (
    ClientConfig,
    ConfigError,
    apply_profile_patch,
    default_config_path,
    original_config_path,
)
from outwarp.i18n import t as tr
from outwarp.tui.tokens import BAD, OK

log = logging.getLogger(__name__)


# (key, label i18n key, hint i18n key, value_getter) per editable field.
# Order = display order. The getter pulls the current value from a ClientConfig
# and renders it as a string the Input widget can show — Textual Inputs are
# text-only, so list-valued fields (dns / bypass_ips / reconnect_delays) get
# joined with ", " on the way in and split back by apply_profile_patch on save.
_FIELDS: list[tuple[str, str, str, Any]] = [
    (
        "name",
        "tui.profile.name",
        "tui.profile.name_hint",
        lambda c: c.name,
    ),
    (
        "mtu",
        "tui.profile.mtu",
        "tui.profile.mtu_hint",
        lambda c: str(c.wireguard.mtu),
    ),
    (
        "dns",
        "tui.profile.dns",
        "tui.profile.dns_hint",
        lambda c: ", ".join(c.wireguard.dns),
    ),
    (
        "client_address",
        "tui.profile.client_address",
        "tui.profile.client_address_hint",
        lambda c: c.wireguard.client_address,
    ),
    (
        "bypass_ips",
        "tui.profile.bypass_ips",
        "tui.profile.bypass_ips_hint",
        lambda c: ", ".join(c.routing.bypass_ips),
    ),
    (
        "reconnect_max_attempts",
        "tui.profile.reconnect_max_attempts",
        "tui.profile.reconnect_max_attempts_hint",
        lambda c: str(c.reconnect.max_attempts),
    ),
    (
        "reconnect_delays",
        "tui.profile.reconnect_delays",
        "tui.profile.reconnect_delays_hint",
        lambda c: ", ".join(str(d) for d in c.reconnect.delays_seconds),
    ),
    (
        "hostile_mode",
        "tui.profile.hostile_mode",
        "tui.profile.hostile_mode_hint",
        lambda c: c.network.hostile_mode,
    ),
]


class ProfileScreen(Screen[None]):
    """Edit the active profile's user-facing fields.

    Validation is delegated to ``apply_profile_patch``: errors surface as an
    English message in the status line, the same wording the GUI editor shows.
    """

    BINDINGS = [
        ("ctrl+s", "save", tr("tui.profile.key_save")),
        ("r", "reset", tr("tui.profile.key_reset")),
        ("escape", "back", tr("tui.key.back")),
        ("q", "back", tr("tui.key.back")),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="profile-scroll"):
            yield Static(f"[bold]{tr('tui.help.edit_profile')}[/bold]", classes="profile-title")
            yield Static(
                f"[dim]{tr('tui.profile.identity_locked')}[/]",
                classes="profile-subtitle",
            )
            cfg = self._current_config()
            for key, label, hint, getter in _FIELDS:
                with Container(classes="profile-row"):
                    yield Static(f"[b]{tr(label)}[/b]", classes="profile-label")
                    yield Static(f"[dim]{tr(hint)}[/]", classes="profile-hint")
                    yield Input(
                        value="" if cfg is None else getter(cfg),
                        id=f"field-{key}",
                        classes="profile-input",
                    )
            with Horizontal(classes="profile-actions"):
                yield Static(
                    f"[dim]{tr('tui.profile.keys')}[/]",
                    id="profile-status",
                )
        yield Footer()

    def _current_config(self) -> ClientConfig | None:
        return getattr(self.app, "config", None)

    # ─── actions ────────────────────────────────────────────────────────────

    def action_save(self) -> None:
        cfg = self._current_config()
        if cfg is None:
            self._set_status(tr("tui.profile.nothing"), ok=False)
            return

        patch: dict[str, Any] = {}
        for key, _label, _hint, _getter in _FIELDS:
            value = self.query_one(f"#field-{key}", Input).value.strip()
            patch[key] = value

        try:
            new_cfg = apply_profile_patch(cfg, patch)
        except ConfigError as exc:
            self._set_status(str(exc), ok=False)
            return

        # Snapshot the pre-edit state once so a future "Reset" always has a
        # baseline, mirroring api.update_profile (api.py:570-577).
        target = default_config_path()
        orig = original_config_path(target)
        if not orig.exists():
            try:
                cfg.save(orig)
            except OSError:
                log.warning("could not snapshot original config")

        try:
            new_cfg.save(target)
        except OSError as exc:
            self._set_status(tr("tui.profile.write_failed", error=exc), ok=False)
            return

        self._reload_manager(new_cfg)
        self._set_status(tr("tui.profile.saved"), ok=True)

    def action_reset(self) -> None:
        target = default_config_path()
        orig = original_config_path(target)
        try:
            new_cfg = ClientConfig.load(orig)
        except ConfigError:
            self._set_status(
                tr("tui.profile.no_original"),
                ok=False,
            )
            return
        try:
            new_cfg.save(target)
        except OSError as exc:
            self._set_status(tr("tui.profile.write_failed", error=exc), ok=False)
            return
        # Repopulate inputs with the restored values so the user sees what
        # they're getting before the manager swap finishes.
        for key, _label, _hint, getter in _FIELDS:
            self.query_one(f"#field-{key}", Input).value = getter(new_cfg)
        self._reload_manager(new_cfg)
        self._set_status(tr("tui.profile.reset_done"), ok=True)

    def action_back(self) -> None:
        self.app.pop_screen()

    # ─── helpers ────────────────────────────────────────────────────────────

    def _reload_manager(self, new_cfg: ClientConfig) -> None:
        # Hand the new config to the app and let start_manager() do the full
        # stop-old / build-new / start-new dance. That path already re-reads
        # settings.json and routes to the right initial screen, so we get the
        # same UX as a fresh launch with the edited profile.
        self.app.config = new_cfg
        try:
            self.app.start_manager()
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors to the user
            log.exception("start_manager failed after profile save")
            self._set_status(tr("tui.profile.reconnect_failed", error=exc), ok=False)

    def _set_status(self, message: str, *, ok: bool) -> None:
        colour = OK if ok else BAD
        marker = "✓" if ok else "✗"
        self.query_one("#profile-status", Static).update(
            f"[{colour}]{marker}[/] {message}"
        )
