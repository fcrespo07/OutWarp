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

log = logging.getLogger(__name__)


# (key, label, hint, value_getter) per editable field.
# Order = display order. The getter pulls the current value from a ClientConfig
# and renders it as a string the Input widget can show — Textual Inputs are
# text-only, so list-valued fields (dns / bypass_ips / reconnect_delays) get
# joined with ", " on the way in and split back by apply_profile_patch on save.
_FIELDS: list[tuple[str, str, str, Any]] = [
    (
        "name",
        "Profile name",
        "Human label for this profile (does not affect the WireGuard interface name).",
        lambda c: c.name,
    ),
    (
        "mtu",
        "MTU",
        "WireGuard MTU. 576-1500; ~1380 is the calibrated value for WG-over-TLS.",
        lambda c: str(c.wireguard.mtu),
    ),
    (
        "dns",
        "DNS servers",
        "Comma-separated IPv4/IPv6 list pushed to the WG interface.",
        lambda c: ", ".join(c.wireguard.dns),
    ),
    (
        "client_address",
        "Client address",
        "WG address assigned by the server (e.g. 10.0.0.42/32). Rarely changed by hand.",
        lambda c: c.wireguard.client_address,
    ),
    (
        "bypass_ips",
        "Bypass IPs / hostnames",
        "Routes that skip the tunnel — typically the server endpoint(s). "
        "IP, CIDR or hostname, comma-separated.",
        lambda c: ", ".join(c.routing.bypass_ips),
    ),
    (
        "reconnect_max_attempts",
        "Reconnect attempts",
        "How many times to retry before giving up (1-100).",
        lambda c: str(c.reconnect.max_attempts),
    ),
    (
        "reconnect_delays",
        "Reconnect delays (s)",
        "Back-off schedule between retries, in seconds. Comma-separated.",
        lambda c: ", ".join(str(d) for d in c.reconnect.delays_seconds),
    ),
]


class ProfileScreen(Screen[None]):
    """Edit the active profile's user-facing fields.

    Validation is delegated to ``apply_profile_patch``: errors surface as a
    Spanish message in the status line so the user sees the exact same wording
    as the GUI editor.
    """

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("r", "reset", "Reset"),
        ("escape", "back", "Back"),
        ("q", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="profile-scroll"):
            yield Static("[bold]Edit profile[/bold]", classes="profile-title")
            yield Static(
                "[dim]Server identity (endpoint, keys, TLS fingerprint) is not editable — "
                "re-import the .owcfg if those change.[/]",
                classes="profile-subtitle",
            )
            cfg = self._current_config()
            for key, label, hint, getter in _FIELDS:
                with Container(classes="profile-row"):
                    yield Static(f"[b]{label}[/b]", classes="profile-label")
                    yield Static(f"[dim]{hint}[/]", classes="profile-hint")
                    yield Input(
                        value="" if cfg is None else getter(cfg),
                        id=f"field-{key}",
                        classes="profile-input",
                    )
            with Horizontal(classes="profile-actions"):
                yield Static(
                    "[dim]Ctrl+S to save · R to reset to import · Esc to go back[/]",
                    id="profile-status",
                )
        yield Footer()

    def _current_config(self) -> ClientConfig | None:
        return getattr(self.app, "config", None)

    # ─── actions ────────────────────────────────────────────────────────────

    def action_save(self) -> None:
        cfg = self._current_config()
        if cfg is None:
            self._set_status("No profile imported — nothing to save.", ok=False)
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
            self._set_status(f"Could not write config: {exc}", ok=False)
            return

        self._reload_manager(new_cfg)
        self._set_status("Saved. Reconnecting with new settings…", ok=True)

    def action_reset(self) -> None:
        target = default_config_path()
        orig = original_config_path(target)
        try:
            new_cfg = ClientConfig.load(orig)
        except ConfigError:
            self._set_status(
                "No original snapshot found — re-import the .owcfg to restore defaults.",
                ok=False,
            )
            return
        try:
            new_cfg.save(target)
        except OSError as exc:
            self._set_status(f"Could not write config: {exc}", ok=False)
            return
        # Repopulate inputs with the restored values so the user sees what
        # they're getting before the manager swap finishes.
        for key, _label, _hint, getter in _FIELDS:
            self.query_one(f"#field-{key}", Input).value = getter(new_cfg)
        self._reload_manager(new_cfg)
        self._set_status("Profile reset to its imported state.", ok=True)

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
            self._set_status(f"Saved, but reconnect failed: {exc}", ok=False)

    def _set_status(self, message: str, *, ok: bool) -> None:
        colour = "#2ee0b3" if ok else "#ff5c7a"
        marker = "✓" if ok else "✗"
        self.query_one("#profile-status", Static).update(
            f"[{colour}]{marker}[/] {message}"
        )
