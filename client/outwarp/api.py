"""
JS <-> Python bridge for the OutWarp client.

Methods on `Api` are exposed to the renderer as ``window.pywebview.api.<method>``.
All return values must be JSON-serialisable.

Python -> JS uses ``_emit(name, payload)`` which fires a ``CustomEvent`` named
``outwarp:<name>`` on the window object. The UI listens with
``window.addEventListener("outwarp:status", ...)``.

Events fired:
  outwarp:status    -> tunnel state changed
  outwarp:stats     -> 1Hz traffic counters (rx/tx bytes per second + totals)
  outwarp:log       -> a single log line was emitted
  outwarp:settings  -> persisted user preferences changed
  outwarp:window    -> window chrome state changed (maximized true/false)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from outwarp import updater
from outwarp.config import (
    ClientConfig,
    ConfigError,
    apply_profile_patch,
    default_config_path,
    import_owcfg_text,
    original_config_path,
)
from outwarp.integrity import IntegrityIssue, likely_av_quarantine
from outwarp.logs import MemoryLogHandler
from outwarp.platforms import PlatformError, get_platform
from outwarp.settings import load_settings as _load_settings_at
from outwarp.settings import save_settings as _save_settings_at
from outwarp.tunnel import TunnelManager, TunnelState
from outwarp.wireguard import get_tunnel_stats

log = logging.getLogger(__name__)


_STATE_TO_JS = {
    TunnelState.DISCONNECTED: "disconnected",
    TunnelState.CONNECTING:   "connecting",
    TunnelState.CONNECTED:    "connected",
    TunnelState.RECONNECTING: "reconnecting",
    TunnelState.FAILED:       "error",
}

# Win32 non-client hit-test codes for the frameless title bar's native drag /
# edge-resize (see Api._native_nc_press).
_WM_NCLBUTTONDOWN = 0x00A1
_HTCAPTION = 2
_RESIZE_HT = {
    "l": 10, "r": 11, "t": 12, "tl": 13, "tr": 14, "b": 15, "bl": 16, "br": 17,
}


# Path resolver kept local so test patches on `outwarp.api.default_config_path`
# continue to redirect settings I/O. The shared `outwarp.settings` module
# accepts an explicit `path` argument that we forward here. KEEP THIS LINE
# in sync with `outwarp.settings.settings_path` — both must derive the file
# from `default_config_path().parent / "settings.json"`; diverging silently
# would let one UI write to a file the other UI never reads.
def _settings_path() -> Path:
    return default_config_path().parent / "settings.json"


def _load_settings() -> dict[str, Any]:
    return _load_settings_at(_settings_path())


def _save_settings(settings: dict[str, Any]) -> None:
    _save_settings_at(settings, _settings_path())


def _autostart_command() -> list[str]:
    """Build the argv that the OS should run on login.

    In a frozen PyInstaller bundle, ``sys.executable`` IS the OutWarp .exe and
    no extra args are needed. In dev mode we re-launch via ``python -m outwarp``
    so the same code path is testable end-to-end without packaging.
    """
    import sys

    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "outwarp"]


def _profile_from_config(cfg: ClientConfig) -> dict[str, Any]:
    """Public-facing projection of a ClientConfig — no private keys.

    Includes the user-editable fields so the profile editor in the UI can be
    populated without a second round-trip.
    """
    wg = cfg.wireguard
    return {
        # id stays tied to the OS interface name (stable); name is the
        # server-assigned, user-editable display label.
        "id": wg.tunnel_name or cfg.server.endpoint,
        "name": cfg.name or wg.tunnel_name or cfg.server.endpoint,
        "endpoint": f"{cfg.server.endpoint}:{cfg.server.port}",
        "fingerprint": cfg.tls.cert_fingerprint_sha256,
        "client_address": wg.client_address,
        "dns": list(wg.dns),
        "mtu": wg.mtu,
        "bypass_ips": list(cfg.routing.bypass_ips),
        "reconnect_max_attempts": cfg.reconnect.max_attempts,
        "reconnect_delays": list(cfg.reconnect.delays_seconds),
        # "" when the profile never expires; ISO date otherwise. Surfaced so the
        # UI can show a badge / warning. Read-only (not user-editable).
        "expires_at": cfg.expires_at,
        "expired": cfg.is_expired(),
    }


class Api:
    """JS-callable bridge. One per process — created by app.py and passed to pywebview."""

    def __init__(
        self,
        memory_handler: MemoryLogHandler,
        manager: TunnelManager | None,
        on_manager_replaced: Callable[[TunnelManager], None] | None = None,
        integrity_issues: list[IntegrityIssue] | None = None,
    ) -> None:
        self._window: Any = None
        # Sticky kill-switch for the Python→JS bridge: flipped True the first
        # time ``evaluate_js`` raises so subsequent ``_emit`` calls no-op
        # cheaply. Kept separate from ``_window`` so window chrome methods
        # (window_minimize/close, pick_owcfg_file) keep working even when the
        # renderer can't accept JS events.
        self._emit_disabled = False
        self._maximized = False
        self._memory_handler = memory_handler
        self._manager: TunnelManager | None = manager
        self._on_manager_replaced = on_manager_replaced
        # Computed once by app.py at startup; surfaced to the UI as a banner.
        # Empty list (default) means "no issues" — the UI hides the banner.
        self._integrity_issues: list[IntegrityIssue] = list(integrity_issues or [])
        # Clean-shutdown callback wired by app.py via set_quit_handler. Used by
        # apply_update() to quit the process after launching the installer so it
        # can replace our files. None in headless/test contexts.
        self._on_quit: Callable[[], None] | None = None

        self._lock = threading.Lock()
        self._settings = _load_settings()
        self._log_seq = 0
        # Snapshot of recent log entries with sequence numbers; the UI polls
        # via get_logs(since=N) on first paint, then receives outwarp:log
        # events for every new line.
        self._logs: deque[dict[str, Any]] = deque(maxlen=2000)
        self._stats = {
            "tx_bps": 0, "rx_bps": 0,
            "tx_total": 0, "rx_total": 0,
            "session_start": 0, "last_handshake": 0,
            "exit_ip": "",
            "exit_location": "",
            "latency_ms": 0,
        }
        self._stats_thread: threading.Thread | None = None
        self._stats_stop = threading.Event()
        self._latency_thread: threading.Thread | None = None
        self._latency_stop = threading.Event()

        if manager is not None:
            manager.add_listener(self._on_state_change)
            manager.allow_tls_intercept = bool(
                self._settings.get("allow_tls_intercept", False)
            )
            manager.auto_reconnect = bool(
                self._settings.get("auto_reconnect", True)
            )

    # ── pywebview wiring ──────────────────────────────────────────────────────

    def bind_window(self, window: Any) -> None:
        """Called once after the window is created so we can push events to JS."""
        # Backfill the log buffer *before* publishing the window — _record_log
        # is a no-op for _emit() while window is None, so we don't waste time
        # calling evaluate_js on a renderer that hasn't started yet
        # (webview.start() runs after this and is what actually boots
        # WebView2). The UI picks the backfill up on first paint via
        # api.get_logs(0); the watcher below covers everything after.
        for line in self._memory_handler.snapshot():
            self._record_log("info", line)
        self._window = window
        # Keep the custom title bar's maximize/restore glyph in sync when the
        # window state changes outside our buttons (Aero Snap, Win+Up, the
        # taskbar). pywebview fires these on the GUI thread.
        try:
            window.events.maximized += self._on_window_maximized
            window.events.restored += self._on_window_restored
        except Exception:
            log.debug("window state events unavailable on this backend", exc_info=True)
        self._start_log_watcher()

    # ── window chrome (custom frameless title bar) ─────────────────────────────

    def get_window_caps(self) -> dict[str, Any]:
        """Tells the UI what the host window can do so it renders the right
        chrome: native edge-resize + system drag are Windows-only; elsewhere
        the title bar falls back to pywebview's drag-region."""
        return {"native_drag_resize": sys.platform == "win32", "maximized": self._maximized}

    def _on_window_maximized(self, *_a: Any) -> None:
        self._maximized = True
        self._emit("window", {"maximized": True})

    def _on_window_restored(self, *_a: Any) -> None:
        self._maximized = False
        self._emit("window", {"maximized": False})

    def window_minimize(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def window_toggle_maximize(self) -> None:
        if self._window is None:
            return
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()

    def window_close(self) -> None:
        # Mirror the native close button: tear the window down, which ends
        # webview.start() and exits the process (the tray "Quit" path does the
        # same teardown via app.py).
        if self._window is not None:
            self._window.destroy()

    def window_start_move(self) -> None:
        """Begin a native window drag (Windows). Gives real Aero Snap and
        double-click-to-maximize, which a JS move loop cannot. No-op elsewhere;
        non-Windows uses the pywebview-drag-region class instead."""
        self._native_nc_press(_HTCAPTION)

    def window_start_resize(self, edge: str) -> None:
        """Begin a native edge/corner resize (Windows). `edge` is one of
        t/b/l/r/tl/tr/bl/br."""
        code = _RESIZE_HT.get(edge)
        if code is not None:
            self._native_nc_press(code)

    def _native_nc_press(self, ht: int) -> None:
        if sys.platform != "win32" or self._window is None:
            return
        native = getattr(self._window, "native", None)
        if native is None:
            return
        try:
            import ctypes

            hwnd = native.Handle.ToInt32()
            user32 = ctypes.windll.user32

            def _do() -> None:
                # Standard WebView2 custom-chrome trick: drop any capture the
                # host holds, then hand the non-client button-down to DefWindowProc
                # so Windows runs its own modal move/resize loop (snap included).
                user32.ReleaseCapture()
                user32.SendMessageW(hwnd, _WM_NCLBUTTONDOWN, ht, 0)

            # Must run on the GUI thread (js_api calls arrive on a worker
            # thread); BeginInvoke posts it and returns without blocking us.
            from System import Action

            native.BeginInvoke(Action(_do))
        except Exception:
            log.debug("native window drag/resize unavailable", exc_info=True)

    def report_ui_error(self, message: str) -> dict[str, Any]:
        """Sink for renderer-side errors (React error boundary, window.onerror,
        unhandledrejection). Without this a JS crash dies in a console nobody
        sees; here it lands in the rotating log file and the in-app log view."""
        try:
            text = str(message)
        except Exception:
            text = "<unstringifiable UI error>"
        log.error("UI: %s", text[:4000])
        return {"ok": True}

    def set_quit_handler(self, fn: Callable[[], None]) -> None:
        """Wire the app's clean-shutdown callback so apply_update() can quit the
        process after launching the installer. Called once by app.py."""
        self._on_quit = fn

    def _maybe_emit_hostile(self) -> None:
        """Read the manager's hostile-detection probe and emit a banner event.

        Defensive against test doubles: a MagicMock manager returns a
        MagicMock here, which fails the isinstance check and gets ignored —
        only real HostileDetection objects (set by Tunnel.connect()) bubble up.
        """
        from outwarp.network import HostileDetection
        detection = getattr(self._manager, "last_hostile_detection", None)
        if not isinstance(detection, HostileDetection) or not detection.hostile:
            return
        try:
            mode = self._manager.config.network.hostile_mode
        except AttributeError:
            mode = "auto"
        self._emit("hostile", {
            "detected": True,
            "reason": detection.reason,
            "mode": mode,
        })

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self._window is None or self._emit_disabled:
            return
        js = (
            "window.dispatchEvent(new CustomEvent('outwarp:"
            + name
            + "', {detail: " + json.dumps(payload) + "}))"
        )
        try:
            self._window.evaluate_js(js)
        except Exception as exc:
            # Flip the sticky kill-switch so subsequent emits no-op. Once
            # evaluate_js raises (typically "Main window failed to start" when
            # the pywebview backend can't boot — missing display, missing
            # WebKit, etc.) it will keep raising forever, and each call costs a
            # pywebview round-trip. We deliberately do NOT clear ``_window``:
            # the window object may still service synchronous methods like
            # minimize/destroy/create_file_dialog, and nulling it would silently
            # break the custom title bar's buttons.
            self._emit_disabled = True
            # Crucially, do NOT use log.exception/log.error here. That would
            # write a new ERROR line to the MemoryLogHandler, which the log
            # watcher (_start_log_watcher) picks up on its next 250ms tick
            # and emits via _emit("log", ...), landing right back in this
            # except branch — infinite recursion that floods outwarp.log with
            # the same traceback every cycle (observed in production).
            sys.stderr.write(
                f"outwarp.api: evaluate_js disabled (outwarp:{name}): {exc}\n"
            )

    # ── status / connect ──────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {**self._status_payload(), "stats": dict(self._stats)}

    def _status_str(self) -> str:
        if self._manager is None:
            return "empty"
        return _STATE_TO_JS.get(self._manager.state, "disconnected")

    def _active_profile_id(self) -> str | None:
        if self._manager is None:
            return None
        return _profile_from_config(self._manager.config)["id"]

    def _error_str(self) -> str | None:
        """Last failure reason for the active tunnel, or None. Coerced to str so
        a stray non-serialisable value can never break the status event."""
        if self._manager is None:
            return None
        err = self._manager.last_error
        return err if isinstance(err, str) else None

    def _attempt_info(self) -> tuple[int, int]:
        """(failed attempts in the current streak, configured max). Coerced to
        int so a non-serialisable value can never break the status event."""
        if self._manager is None:
            return 0, 0
        a = getattr(self._manager, "attempt", 0)
        attempt = a if isinstance(a, int) else 0
        try:
            max_attempts = int(self._manager.config.reconnect.max_attempts)
        except (TypeError, ValueError, AttributeError):
            max_attempts = 0
        return attempt, max_attempts

    def _status_payload(self) -> dict[str, Any]:
        attempt, max_attempts = self._attempt_info()
        phase = ""
        if self._manager is not None:
            p = getattr(self._manager, "phase", "")
            if isinstance(p, str):
                phase = p
        return {
            "status": self._status_str(),
            "active_profile_id": self._active_profile_id(),
            "error": self._error_str(),
            "attempt": attempt,
            "max_attempts": max_attempts,
            # "" between attempts; "resolve"|"tls"|"wg"|"ws"|"done" while
            # connecting. The UI uses it to drive the connecting stepper.
            "phase": phase,
        }

    def connect(self, profile_id: str | None = None) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}
        if self._manager.config.is_expired():
            msg = (
                f"Este perfil caducó el {self._manager.config.expires_at}. "
                "Pide uno nuevo al administrador del servidor."
            )
            self._record_log("error", msg)
            return {"ok": False, "error": msg}
        self._manager.start()
        return {"ok": True}

    def disconnect(self) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}
        threading.Thread(
            target=self._manager.stop, daemon=True, name="api-disconnect"
        ).start()
        return {"ok": True}

    def reconnect(self) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}
        # Capture the manager NOW so a concurrent import_profile() swap can't
        # leave us stopping the old one and starting a fresh, already-running
        # replacement (which TunnelManager.start() may or may not survive).
        mgr = self._manager
        def _restart() -> None:
            mgr.stop()
            mgr.start()
        threading.Thread(target=_restart, daemon=True, name="api-reconnect").start()
        return {"ok": True}

    def _on_state_change(self, state: TunnelState) -> None:
        payload = self._status_payload()
        # Trust the state we were handed over a re-read of the manager.
        payload["status"] = _STATE_TO_JS.get(state, "disconnected")
        self._emit("status", payload)
        self._sync_kill_switch(state)
        # CONNECTING/CONNECTED is when the Tunnel has had a chance to run its
        # hostile-network probe; surface the result so the UI banner can warn
        # the user that DNS interception was detected (and that wstunnel is
        # now using 1.1.1.1 under the hood).
        if state in (TunnelState.CONNECTING, TunnelState.CONNECTED):
            self._maybe_emit_hostile()
        if state is TunnelState.CONNECTED:
            self._stats["session_start"] = time.time()
            self._stats["last_handshake"] = time.time()
            self._stats["exit_ip"] = ""
            self._stats["exit_location"] = ""
            self._stats["latency_ms"] = 0
            self._start_stats_loop()
            self._start_exit_ip_probe()
            self._start_latency_loop()
        else:
            self._stop_stats_loop()
            self._stop_latency_loop()
            self._stats["exit_ip"] = ""
            self._stats["exit_location"] = ""
            self._stats["latency_ms"] = 0
            if state in (TunnelState.DISCONNECTED, TunnelState.FAILED):
                self._stats["session_start"] = 0

    def _sync_kill_switch(self, state: TunnelState) -> None:
        """Engage/release the kill switch in response to a tunnel state change.

        Engagement happens when the tunnel is unexpectedly down — the
        RECONNECTING attempt window and the terminal FAILED state. Released on
        a successful CONNECTED or a clean DISCONNECTED (user pressed stop).
        CONNECTING (a fresh startup attempt) is left alone so a previously-
        engaged switch isn't released the moment the user clicks Connect.
        """
        if not bool(self._settings.get("kill_switch", False)):
            return
        if self._manager is None:
            return
        try:
            if state in (TunnelState.RECONNECTING, TunnelState.FAILED):
                allowlist = list(self._manager.config.routing.bypass_ips)
                if not allowlist:
                    log.warning(
                        "kill_switch: no bypass_ips in profile — refusing to "
                        "engage (would lock the user out with no recovery path)"
                    )
                    return
                get_platform().engage_kill_switch(allowlist)
                self._record_log("warn", "kill switch engaged — outbound traffic blocked")
            elif state in (TunnelState.CONNECTED, TunnelState.DISCONNECTED):
                get_platform().release_kill_switch()
        except PlatformError as exc:
            log.warning("kill_switch sync failed: %s", exc)
            self._record_log("error", f"kill switch error: {exc}")

    # ── profiles ──────────────────────────────────────────────────────────────

    def list_profiles(self) -> list[dict[str, Any]]:
        # Single-profile model: returns either 0 entries (no profile imported)
        # or 1 (the active one). The list shape is kept so the UI can render
        # uniformly and so a future multi-profile rework doesn't break callers.
        if self._manager is None:
            return []
        return [_profile_from_config(self._manager.config)]

    # An .owcfg is a small JSON document (~1–2 KB). Anything past this is either
    # a wrong file the user dropped or a malformed paste — reject before parsing.
    _MAX_OWCFG_BYTES = 256 * 1024

    def import_profile(self, file_content: str) -> dict[str, Any]:
        """Accept an .owcfg payload as text. Stores it as the active config."""
        if not isinstance(file_content, str) or not file_content.strip():
            return {"ok": False, "error": "Empty or invalid .owcfg content"}
        if len(file_content.encode("utf-8", "ignore")) > self._MAX_OWCFG_BYTES:
            return {"ok": False, "error": "This file is too large to be a valid .owcfg"}
        try:
            # Parse first so an already-expired profile is rejected before it
            # ever touches disk.
            parsed = ClientConfig.loads(file_content)
        except ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        if parsed.is_expired():
            return {
                "ok": False,
                "error": f"Este perfil caducó el {parsed.expires_at}. "
                         "Pide uno nuevo al administrador del servidor.",
            }
        try:
            # Pass the resolved path explicitly so a test patching
            # ``outwarp.api.default_config_path`` actually redirects the write
            # — import_owcfg_text would otherwise resolve its own
            # ``outwarp.config.default_config_path`` and clobber the real
            # user config (we hit that during local validation).
            cfg = import_owcfg_text(file_content, dest=default_config_path())
        except ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("import_profile failed")
            return {"ok": False, "error": str(exc)}

        # Swap manager: stop old, create new, notify the orchestrator.
        old = self._manager
        if old is not None:
            old.stop()
        new_manager = TunnelManager(
            cfg,
            allow_tls_intercept=bool(self._settings.get("allow_tls_intercept", False)),
            auto_reconnect=bool(self._settings.get("auto_reconnect", True)),
        )
        new_manager.add_listener(self._on_state_change)
        self._manager = new_manager
        if self._on_manager_replaced is not None:
            try:
                self._on_manager_replaced(new_manager)
            except Exception:
                log.exception("on_manager_replaced raised")

        prof = _profile_from_config(cfg)
        self._record_log("info", f"profile imported: {prof['name']}")
        self._emit("status", self._status_payload())
        return {"ok": True, "profile": prof}

    def remove_profile(self, profile_id: str) -> dict[str, Any]:
        # Single-profile model: `profile_id` is ignored. There is at most one
        # active config, so "remove" means stop the tunnel and forget it.
        if self._manager is None:
            return {"ok": True}
        self._manager.stop()
        self._manager = None
        try:
            default_config_path().unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete config: %s", exc)
        self._emit("status", self._status_payload())
        return {"ok": True}

    def set_active_profile(self, profile_id: str) -> dict[str, Any]:
        # Single-profile model: there is nothing to switch between. Accept and
        # ignore so the UI can call this without special-casing.
        return {"ok": True}

    def update_profile(self, profile_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply user edits (name, MTU, DNS, IP, routing, reconnect) to the
        active profile. Persists config.json and — if the tunnel was up —
        reconnects so the new values take effect."""
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}
        if not isinstance(patch, dict):
            return {"ok": False, "error": "invalid patch"}

        current = self._manager.config
        try:
            new_cfg = apply_profile_patch(current, patch)
        except ConfigError as exc:
            return {"ok": False, "error": str(exc)}

        # Profiles imported before profile-editing existed have no pristine
        # snapshot; capture the pre-edit state once so "reset" still works.
        orig_path = original_config_path(default_config_path())
        if not orig_path.exists():
            try:
                current.save(orig_path)
            except OSError:
                log.warning("could not snapshot original config")

        try:
            new_cfg.save(default_config_path())
        except OSError as exc:
            return {"ok": False, "error": f"no se pudo guardar la configuración: {exc}"}

        try:
            self._replace_manager(new_cfg)
        except Exception as exc:
            log.exception("update_profile: manager swap failed")
            return {"ok": False, "error": str(exc)}

        prof = _profile_from_config(new_cfg)
        self._record_log("info", f"profile settings updated: {prof['name']}")
        return {"ok": True, "profile": prof}

    def reset_profile(self, profile_id: str) -> dict[str, Any]:
        """Restore the profile to the exact state it had when the .owcfg was
        imported, discarding every local edit."""
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}

        orig_path = original_config_path(default_config_path())
        try:
            new_cfg = ClientConfig.load(orig_path)
        except ConfigError:
            return {
                "ok": False,
                "error": "No hay una configuración original guardada para este perfil. "
                         "Vuelve a importar el .owcfg para restaurarla.",
            }

        try:
            new_cfg.save(default_config_path())
        except OSError as exc:
            return {"ok": False, "error": f"no se pudo guardar la configuración: {exc}"}

        try:
            self._replace_manager(new_cfg)
        except Exception as exc:
            log.exception("reset_profile: manager swap failed")
            return {"ok": False, "error": str(exc)}

        prof = _profile_from_config(new_cfg)
        self._record_log("info", f"profile settings reset to defaults: {prof['name']}")
        return {"ok": True, "profile": prof}

    def _replace_manager(self, cfg: ClientConfig) -> None:
        """Swap in a TunnelManager for `cfg`. If the tunnel was active, the old
        one is stopped and the new one started (in a background thread so the
        bridge call returns immediately)."""
        old = self._manager
        was_active = old is not None and old.state in (
            TunnelState.CONNECTED,
            TunnelState.CONNECTING,
            TunnelState.RECONNECTING,
        )
        new_manager = TunnelManager(
            cfg,
            allow_tls_intercept=bool(self._settings.get("allow_tls_intercept", False)),
            auto_reconnect=bool(self._settings.get("auto_reconnect", True)),
        )
        new_manager.add_listener(self._on_state_change)
        self._manager = new_manager
        if self._on_manager_replaced is not None:
            try:
                self._on_manager_replaced(new_manager)
            except Exception:
                log.exception("on_manager_replaced raised")

        def _switch() -> None:
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    log.exception("error stopping previous manager")
            if was_active:
                new_manager.start()

        threading.Thread(target=_switch, daemon=True, name="api-profile-swap").start()
        self._emit("status", self._status_payload())

    # ── logs ──────────────────────────────────────────────────────────────────

    def get_logs(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._logs if e["seq"] > since]

    def clear_logs(self) -> dict[str, Any]:
        """Empty the in-memory log buffer the UI reads from. New lines from the
        running tunnel keep flowing in afterwards."""
        with self._lock:
            self._logs.clear()
        return {"ok": True}

    def export_logs(self) -> dict[str, Any]:
        """Write the current log buffer to a file the user picks via the native
        save dialog."""
        if self._window is None:
            return {"ok": False, "error": "no window"}
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename="outwarp-logs.txt"
            )
        except Exception as exc:
            log.exception("export_logs: file dialog failed")
            return {"ok": False, "error": str(exc)}
        if not result:
            return {"ok": False, "error": "cancelled"}
        path = result if isinstance(result, str) else result[0]
        try:
            with self._lock:
                lines = [
                    f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts']))} "
                    f"[{e['level'].upper()}] {e['msg']}"
                    for e in self._logs
                ]
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": path}

    def _record_log(self, level: str, msg: str) -> None:
        with self._lock:
            self._log_seq += 1
            entry = {"seq": self._log_seq, "ts": time.time(), "level": level, "msg": msg}
            self._logs.append(entry)
        self._emit("log", entry)

    def _start_log_watcher(self) -> None:
        """Poll the MemoryLogHandler 4×/s and emit each new line as an event."""
        last_count = len(self._memory_handler.snapshot())

        def _loop() -> None:
            nonlocal last_count
            while True:
                snapshot = self._memory_handler.snapshot()
                if len(snapshot) < last_count:
                    last_count = 0  # buffer rotated
                if len(snapshot) > last_count:
                    for line in snapshot[last_count:]:
                        # rough level inference: lines from MemoryLogHandler are
                        # already formatted "ts [LEVEL] name: msg"
                        level = "info"
                        for token in ("ERROR", "WARNING", "DEBUG"):
                            if f"[{token}]" in line:
                                level = token.lower().replace("warning", "warn")
                                break
                        self._record_log(level, line)
                    last_count = len(snapshot)
                time.sleep(0.25)

        threading.Thread(target=_loop, daemon=True, name="outwarp-log-watcher").start()

    # ── settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def navigate(self, screen: str) -> dict[str, Any]:
        """Ask the UI to switch screens. Used by the tray's 'View logs' item;
        the JS App listens for the outwarp:navigate event."""
        self._emit("navigate", {"screen": str(screen)})
        return {"ok": True}

    # ── integrity ─────────────────────────────────────────────────────────────

    def get_integrity(self) -> dict[str, Any]:
        """Report whether any critical bundled file is missing/empty.

        Computed once at startup by app.py and cached here — the UI shows a
        banner with AV-specific guidance when ``likely_av`` is True.
        """
        issues = self._integrity_issues
        return {
            "ok": not issues,
            "likely_av": likely_av_quarantine(issues),
            "issues": [i.to_dict() for i in issues],
        }

    # ── about ─────────────────────────────────────────────────────────────────

    def get_app_info(self) -> dict[str, Any]:
        """Static metadata for the About screen. Pure read-only — no I/O."""
        import platform as platform_mod
        import sys

        from outwarp import __version__

        return {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": platform_mod.platform(),
            "repo_url": "https://github.com/fcrespo07/OutWarp",
            "license": "MIT",
            "third_party": [
                {"name": "wstunnel",  "license": "BSD-3-Clause",
                 "url": "https://github.com/erebe/wstunnel"},
                {"name": "WireGuard", "license": "GPL-2.0",
                 "url": "https://www.wireguard.com/"},
                {"name": "pystray",   "license": "LGPL-3.0",
                 "url": "https://github.com/moses-palmer/pystray"},
                {"name": "pywebview", "license": "BSD-3-Clause",
                 "url": "https://pywebview.flowrl.com/"},
            ],
        }

    def open_url(self, url: str) -> dict[str, Any]:
        """Open `url` in the user's default browser. Refuses non-http(s) so a
        compromised renderer can't ask us to launch arbitrary handlers
        (file://, javascript:, custom protocol handlers)."""
        import webbrowser

        if not isinstance(url, str) or not (
            url.startswith("https://") or url.startswith("http://")
        ):
            return {"ok": False, "error": "only http(s) URLs are allowed"}
        try:
            webbrowser.open(url, new=2)
        except Exception as exc:
            log.exception("open_url failed for %s", url)
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    # ── updates ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _prefer_full_installer() -> bool:
        """True when a server bundle sits next to this client install.

        The slim client installer omits the server bundle, so applying it over a
        machine that runs both apps would leave the server stale. In that case
        prefer the combined installer. Only meaningful in a frozen one-folder
        build, where sys.executable is {app}\\client\\outwarp.exe and the server
        (if installed) is {app}\\server\\.
        """
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return False
        try:
            app_dir = Path(sys.executable).resolve().parent.parent
            return (app_dir / "server" / "outwarp-server-gui.exe").exists()
        except Exception:
            return False

    def check_for_updates(self) -> dict[str, Any]:
        """Query GitHub Releases for a newer version. Synchronous (5s timeout,
        never raises). On Linux there is no in-app apply, so the manual install
        command is attached for the UI to display."""
        from outwarp import __version__

        result = updater.check_for_update(__version__, prefer_full=self._prefer_full_installer())
        if sys.platform != "win32":
            result["manual"] = True
            result["command"] = updater.LINUX_UPDATE_COMMAND
        return result

    def apply_update(self) -> dict[str, Any]:
        """Windows only: download the latest installer, bring the tunnel down,
        launch the installer elevated and quit so it can replace our files (its
        post-install step relaunches us). On Linux returns the manual command —
        there is no .exe to apply and the GUI can't run non-interactive sudo.

        Returns immediately; progress is reported via the outwarp:update event
        ({phase, progress, latest, error})."""
        if sys.platform != "win32":
            return {
                "ok": False,
                "manual": True,
                "command": updater.LINUX_UPDATE_COMMAND,
            }
        threading.Thread(
            target=self._run_update, daemon=True, name="api-apply-update"
        ).start()
        return {"ok": True}

    def _run_update(self) -> None:
        from outwarp import __version__

        self._emit("update", {"phase": "checking", "progress": 0})
        info = updater.check_for_update(__version__, prefer_full=self._prefer_full_installer())
        if info.get("error"):
            self._emit("update", {"phase": "error", "error": info["error"]})
            return
        if not info.get("available"):
            self._emit("update", {"phase": "current", "latest": info.get("latest", "")})
            return
        url = info.get("asset_url")
        if not url:
            self._emit("update", {
                "phase": "error",
                "error": "the latest release has no Windows installer asset",
            })
            return

        latest = info.get("latest", "")
        dest = Path(tempfile.gettempdir()) / (info.get("asset_name") or "OutWarpSetup.exe")
        try:
            self._emit("update", {"phase": "downloading", "progress": 0, "latest": latest})
            updater.download_installer(
                url,
                dest,
                lambda pct: self._emit(
                    "update", {"phase": "downloading", "progress": pct, "latest": latest}
                ),
            )
        except Exception as exc:
            log.exception("update download failed")
            self._emit("update", {"phase": "error", "error": str(exc)})
            return

        # Verify the download against the release's published SHA256SUMS before
        # we run it. A mismatch — or a manifest that couldn't be fetched, or
        # one that doesn't list this asset — means a corrupted or tampered file
        # / a downgrade attempt: refuse. Only releases with no manifest at all
        # (legacy, pre-SHA256SUMS) pass through with ok=True.
        self._emit("update", {"phase": "verifying", "latest": latest})
        try:
            ok, detail = updater.verify_download(
                dest, info.get("asset_name") or "", info.get("checksums_url") or ""
            )
        except Exception as exc:
            log.exception("update checksum verification crashed")
            ok, detail = False, str(exc)
        if not ok:
            log.error("update integrity check failed: %s", detail)
            self._emit("update", {
                "phase": "error",
                "error": f"La verificación de integridad falló ({detail}). "
                         "No se aplicará la actualización.",
            })
            return
        log.info("update integrity: %s", detail)

        self._emit("update", {"phase": "applying", "latest": latest})

        # Bring the tunnel down cleanly first so wstunnel.exe and the WireGuard
        # service/routes are released — otherwise the installer can't replace
        # files and a child process would be orphaned.
        if self._manager is not None:
            try:
                self._manager.stop()
            except Exception:
                log.exception("tunnel stop before update failed (continuing)")

        if not self._launch_installer(dest):
            self._emit("update", {
                "phase": "error",
                "error": "could not launch the installer (elevation declined?)",
            })
            return

        # Hand off to the installer and quit so it can replace our files and
        # relaunch us via its post-install 'Launch OutWarp Client' step.
        self._quit_for_update()

    # /AUTOUPDATE=1 tells the installer to relaunch the client when it finishes
    # (outwarp.iss [Run] → IsAutoUpdate); the silent flags suppress the wizard.
    # Because the client is already elevated (app._ensure_elevated runs at
    # startup), the powershell helper below inherits that elevation with no
    # extra UAC prompt — so the whole update applies in the background and the
    # app just restarts itself.
    _INSTALLER_SILENT_ARGS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /AUTOUPDATE=1"

    def _launch_installer(self, path: Path) -> bool:
        """Spawn a detached helper that waits for THIS process to exit, then
        runs the installer. Returns True on successful spawn.

        We can't just ShellExecute the installer and immediately quit: Inno
        Setup probes our AppMutex (Global\\OutWarpClient, see outwarp.iss) at
        startup, and /VERYSILENT mode has no retry dialog. If the mutex is
        still held when Inno checks it — and api.shutdown() can take a second
        or two — Inno silently skips locked files (outwarp.exe and the mapped
        _internal/*.pyd next to it) and the "updated" install keeps running
        the old binary. The user sees the app close and reopen at the OLD
        version. This bit users updating v0.3.0 → v0.4.0.

        The fix: have a tiny powershell child watch our PID, wait for it to
        die, then launch the installer. By that point our mutex is released
        and the .exe is unmapped, so Inno can replace every file.
        """
        pid = os.getpid()
        # Single-quote-escape the path for the PS string literal so paths
        # containing apostrophes (rare but possible under %TEMP%) survive.
        path_esc = str(path).replace("'", "''")
        ps_cmd = (
            "$ErrorActionPreference='SilentlyContinue';"
            f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue;"
            # Brief settle so Windows finishes unmapping the .exe before Inno
            # opens it for write. Belt-and-braces — Wait-Process already
            # returns post-exit.
            "Start-Sleep -Milliseconds 750;"
            f"Start-Process -FilePath '{path_esc}' "
            f"-ArgumentList '{self._INSTALLER_SILENT_ARGS}' -Verb RunAs"
        )
        # DETACHED_PROCESS so the helper survives our exit; CREATE_NO_WINDOW
        # so no console flashes.
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | 0x08000000  # CREATE_NO_WINDOW
        )
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-WindowStyle", "Hidden",
                    "-Command", ps_cmd,
                ],
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception:
            log.exception("could not spawn deferred installer launcher")
            return False
        return True

    def _quit_for_update(self) -> None:
        if self._on_quit is not None:
            try:
                self._on_quit()
                return
            except Exception:
                log.exception("quit handler failed during update")
        # Fallback (no handler wired, e.g. headless): best-effort hard exit so
        # the file locks release for the installer.
        try:
            self.shutdown()
        finally:
            os._exit(0)

    def set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            before = dict(self._settings)
            if isinstance(patch, dict):
                for k, v in patch.items():
                    if k in self._settings:
                        self._settings[k] = v
            snapshot = dict(self._settings)
            try:
                _save_settings(snapshot)
            except OSError as exc:
                log.warning("could not persist settings: %s", exc)

        # Side effects after the lock is released: registry / desktop-file I/O
        # can take a moment and we don't want to block other API calls.
        if isinstance(patch, dict) and self._manager:
            if "allow_tls_intercept" in patch:
                self._manager.allow_tls_intercept = bool(snapshot["allow_tls_intercept"])
            if "auto_reconnect" in patch:
                self._manager.auto_reconnect = bool(snapshot["auto_reconnect"])

        autostart_error: str | None = None
        if isinstance(patch, dict) and "start_at_boot" in patch:
            was = bool(before.get("start_at_boot", False))
            now = bool(snapshot.get("start_at_boot", False))
            if was != now:
                try:
                    plat = get_platform()
                    if now:
                        plat.install_autostart(_autostart_command())
                    else:
                        plat.uninstall_autostart()
                except PlatformError as exc:
                    # Side effect failed — roll back the persisted value so we
                    # don't lie about a non-existent registration.
                    log.warning("autostart toggle failed: %s", exc)
                    autostart_error = str(exc)
                    with self._lock:
                        self._settings["start_at_boot"] = was
                        snapshot = dict(self._settings)
                        try:
                            _save_settings(snapshot)
                        except OSError:
                            log.warning("could not roll back start_at_boot")

        kill_switch_error: str | None = None
        if isinstance(patch, dict) and "kill_switch" in patch:
            was = bool(before.get("kill_switch", False))
            now = bool(snapshot.get("kill_switch", False))
            if was != now:
                try:
                    plat = get_platform()
                    if now:
                        # Activated mid-session: engage NOW if the tunnel is
                        # already down, so the user isn't leaking while the
                        # next state change waits to fire.
                        if (
                            self._manager is not None
                            and self._manager.state in (
                                TunnelState.RECONNECTING, TunnelState.FAILED,
                            )
                        ):
                            allowlist = list(
                                self._manager.config.routing.bypass_ips
                            )
                            if allowlist:
                                plat.engage_kill_switch(allowlist)
                    else:
                        # Always release on disable — even if we never engaged
                        # — to recover from any stale rule.
                        plat.release_kill_switch()
                except PlatformError as exc:
                    log.warning("kill_switch toggle failed: %s", exc)
                    kill_switch_error = str(exc)
                    with self._lock:
                        self._settings["kill_switch"] = was
                        snapshot = dict(self._settings)
                        try:
                            _save_settings(snapshot)
                        except OSError:
                            log.warning("could not roll back kill_switch")

        self._emit("settings", snapshot)
        if autostart_error is not None:
            return {"ok": False, "error": autostart_error, "settings": snapshot}
        if kill_switch_error is not None:
            return {"ok": False, "error": kill_switch_error, "settings": snapshot}
        return {"ok": True, "settings": snapshot}

    # ── stats ─────────────────────────────────────────────────────────────────

    def _start_stats_loop(self) -> None:
        if self._stats_thread is not None and self._stats_thread.is_alive():
            return
        self._stats_stop.clear()

        def _loop() -> None:
            # Bind once: ``self._manager`` can be flipped to None by
            # ``forget_profile`` between the truthy check and the ``.config``
            # deref, which would AttributeError this thread silently.
            mgr = self._manager
            tunnel_name = mgr.config.wireguard.tunnel_name if mgr else ""
            prev_rx, prev_tx, prev_ts = 0, 0, 0.0
            while not self._stats_stop.is_set():
                now = time.time()
                snap = get_tunnel_stats(tunnel_name) if tunnel_name else None
                if snap is not None:
                    if prev_ts > 0:
                        dt = max(now - prev_ts, 0.001)
                        rx_bps = max(0, int((snap.rx_bytes - prev_rx) / dt))
                        tx_bps = max(0, int((snap.tx_bytes - prev_tx) / dt))
                    else:
                        rx_bps = tx_bps = 0
                    self._stats["rx_bps"] = rx_bps
                    self._stats["tx_bps"] = tx_bps
                    self._stats["rx_total"] = snap.rx_bytes
                    self._stats["tx_total"] = snap.tx_bytes
                    if snap.latest_handshake is not None:
                        self._stats["last_handshake"] = snap.latest_handshake
                    prev_rx, prev_tx, prev_ts = snap.rx_bytes, snap.tx_bytes, now
                # Always emit so the UI has a heartbeat — even if wg isn't
                # readable (e.g. running tunnel without privileges) the dial
                # / session timer keeps ticking.
                self._emit("stats", dict(self._stats))
                # Re-broadcast status too: a cheap watchdog in case an earlier
                # evaluate_js call was dropped by the webview backend before
                # the page was ready to receive it.
                self._emit("status", self._status_payload())
                time.sleep(1.0)

        self._stats_thread = threading.Thread(
            target=_loop, daemon=True, name="outwarp-stats"
        )
        self._stats_thread.start()

    def _stop_stats_loop(self) -> None:
        self._stats_stop.set()
        self._stats_thread = None

    def _start_exit_ip_probe(self) -> None:
        """After connecting, query our public IP so the UI can show the user
        their traffic is actually exiting through the tunnel, then geolocate
        it. Best-effort: a few retries (routing may not be up the instant we
        go CONNECTED), short timeouts, every failure swallowed."""
        def _probe() -> None:
            import urllib.request
            ip = ""
            for _ in range(3):
                if self._stats.get("session_start", 0) == 0:
                    return  # disconnected before we got an answer
                try:
                    with urllib.request.urlopen(
                        "https://api.ipify.org", timeout=5
                    ) as resp:
                        ip = resp.read().decode("utf-8", "replace").strip()
                    if ip:
                        self._stats["exit_ip"] = ip
                        self._emit("stats", dict(self._stats))
                        break
                except Exception:
                    pass
                time.sleep(2)
            if not ip or self._stats.get("session_start", 0) == 0:
                return
            try:
                with urllib.request.urlopen(
                    f"https://ipapi.co/{ip}/json/", timeout=5
                ) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                loc = ", ".join(
                    filter(None, [data.get("city"), data.get("country_name")])
                )
                if loc and self._stats.get("session_start", 0) != 0:
                    self._stats["exit_location"] = loc
                    self._emit("stats", dict(self._stats))
            except Exception:
                pass

        threading.Thread(target=_probe, daemon=True, name="outwarp-exit-ip").start()

    def _start_latency_loop(self) -> None:
        """Ping the WG peer (the server's in-tunnel IP) every 10s while
        connected. Best-effort: any failure leaves latency at 0 and the UI
        renders a dash."""
        if self._latency_thread is not None and self._latency_thread.is_alive():
            return
        if self._manager is None:
            return
        target = self._manager.config.tunnel.remote_host
        if not target:
            return
        self._latency_stop.clear()

        def _loop(host: str) -> None:
            from outwarp.network import measure_latency_ms
            while not self._latency_stop.is_set():
                ms = measure_latency_ms(host)
                self._stats["latency_ms"] = int(ms) if ms is not None else 0
                self._emit("stats", dict(self._stats))
                if self._latency_stop.wait(10):
                    break

        self._latency_thread = threading.Thread(
            target=_loop, args=(target,), daemon=True, name="outwarp-latency",
        )
        self._latency_thread.start()

    def _stop_latency_loop(self) -> None:
        self._latency_stop.set()
        self._latency_thread = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._stop_stats_loop()
        self._stop_latency_loop()
        if self._manager is not None:
            try:
                self._manager.stop()
            except Exception:
                log.exception("manager.stop failed during shutdown")
        # Release the kill switch on the way out — leaving it engaged would
        # leave the user offline until they figure out where the rule lives.
        try:
            get_platform().release_kill_switch()
        except Exception:
            log.exception("kill-switch release during shutdown failed")
