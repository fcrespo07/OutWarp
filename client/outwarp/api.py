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
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from outwarp.config import (
    ClientConfig,
    ConfigError,
    default_config_path,
    import_owcfg,
)
from outwarp.logs import MemoryLogHandler
from outwarp.tunnel import TunnelManager, TunnelState

log = logging.getLogger(__name__)


_STATE_TO_JS = {
    TunnelState.DISCONNECTED: "disconnected",
    TunnelState.CONNECTING:   "connecting",
    TunnelState.CONNECTED:    "connected",
    TunnelState.RECONNECTING: "connecting",  # UI treats both alike
    TunnelState.FAILED:       "error",
}


def _settings_path() -> Path:
    return default_config_path().parent / "settings.json"


def _default_settings() -> dict[str, Any]:
    return {
        "language": "es",
        "theme": "auto",
        "advanced": False,
        "start_at_boot": False,
        "auto_reconnect": True,
        "kill_switch": False,
    }


def _load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return _default_settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_settings()
    merged = _default_settings()
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in merged})
    return merged


def _save_settings(settings: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _profile_from_config(cfg: ClientConfig) -> dict[str, Any]:
    """Public-facing projection of a ClientConfig — no private keys."""
    return {
        "id": cfg.wireguard.tunnel_name or cfg.server.endpoint,
        "name": cfg.wireguard.tunnel_name or cfg.server.endpoint,
        "endpoint": f"{cfg.server.endpoint}:{cfg.server.port}",
        "fingerprint": cfg.tls.cert_fingerprint_sha256,
        "client_address": cfg.wireguard.client_address,
        "dns": cfg.wireguard.dns,
    }


class Api:
    """JS-callable bridge. One per process — created by app.py and passed to pywebview."""

    def __init__(
        self,
        memory_handler: MemoryLogHandler,
        manager: TunnelManager | None,
        on_manager_replaced: Callable[[TunnelManager], None] | None = None,
    ) -> None:
        self._window: Any = None
        self._memory_handler = memory_handler
        self._manager: TunnelManager | None = manager
        self._on_manager_replaced = on_manager_replaced

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
        }
        self._stats_thread: threading.Thread | None = None
        self._stats_stop = threading.Event()

        if manager is not None:
            manager.add_listener(self._on_state_change)

    # ── pywebview wiring ──────────────────────────────────────────────────────

    def bind_window(self, window: Any) -> None:
        """Called once after the window is created so we can push events to JS."""
        self._window = window
        # Backfill: replay the MemoryLogHandler buffer so the UI's log view has
        # context as soon as it mounts.
        for line in self._memory_handler.snapshot():
            self._record_log("info", line)
        # Start the watcher that streams real log lines as they arrive.
        self._start_log_watcher()

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self._window is None:
            return
        js = (
            "window.dispatchEvent(new CustomEvent('outwarp:"
            + name
            + "', {detail: " + json.dumps(payload) + "}))"
        )
        try:
            self._window.evaluate_js(js)
        except Exception:
            log.exception("evaluate_js failed for outwarp:%s", name)

    # ── status / connect ──────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status_str(),
            "active_profile_id": self._active_profile_id(),
            "stats": dict(self._stats),
        }

    def _status_str(self) -> str:
        if self._manager is None:
            return "empty"
        return _STATE_TO_JS.get(self._manager.state, "disconnected")

    def _active_profile_id(self) -> str | None:
        if self._manager is None:
            return None
        return _profile_from_config(self._manager.config)["id"]

    def connect(self, profile_id: str | None = None) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "no profile imported"}
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
        def _restart() -> None:
            self._manager.stop()
            self._manager.start()
        threading.Thread(target=_restart, daemon=True, name="api-reconnect").start()
        return {"ok": True}

    def _on_state_change(self, state: TunnelState) -> None:
        ui = _STATE_TO_JS.get(state, "disconnected")
        self._emit("status", {
            "status": ui,
            "active_profile_id": self._active_profile_id(),
        })
        if state is TunnelState.CONNECTED:
            self._stats["session_start"] = time.time()
            self._stats["last_handshake"] = time.time()
            self._start_stats_loop()
        else:
            self._stop_stats_loop()
            if state in (TunnelState.DISCONNECTED, TunnelState.FAILED):
                self._stats["session_start"] = 0

    # ── profiles ──────────────────────────────────────────────────────────────

    def list_profiles(self) -> list[dict[str, Any]]:
        if self._manager is None:
            return []
        return [_profile_from_config(self._manager.config)]

    def import_profile(self, file_content: str) -> dict[str, Any]:
        """Accept an .owcfg payload as text. Stores it as the active config."""
        tmp = tempfile.NamedTemporaryFile(
            prefix="outwarp-import-", suffix=".owcfg", delete=False, mode="w",
            encoding="utf-8",
        )
        try:
            tmp.write(file_content)
            tmp.close()
            try:
                cfg = import_owcfg(Path(tmp.name))
            except ConfigError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                log.exception("import_profile failed")
                return {"ok": False, "error": str(exc)}
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass

        # Swap manager: stop old, create new, notify the orchestrator.
        old = self._manager
        if old is not None:
            old.stop()
        new_manager = TunnelManager(cfg)
        new_manager.add_listener(self._on_state_change)
        self._manager = new_manager
        if self._on_manager_replaced is not None:
            try:
                self._on_manager_replaced(new_manager)
            except Exception:
                log.exception("on_manager_replaced raised")

        prof = _profile_from_config(cfg)
        self._record_log("info", f"profile imported: {prof['name']}")
        self._emit("status", {
            "status": self._status_str(),
            "active_profile_id": prof["id"],
        })
        return {"ok": True, "profile": prof}

    def remove_profile(self, profile_id: str) -> dict[str, Any]:
        # Multi-profile management isn't supported yet — there is at most one
        # active config. "Remove" therefore means: stop the tunnel and forget it.
        if self._manager is None:
            return {"ok": True}
        self._manager.stop()
        self._manager = None
        try:
            default_config_path().unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete config: %s", exc)
        self._emit("status", {"status": "empty", "active_profile_id": None})
        return {"ok": True}

    def set_active_profile(self, profile_id: str) -> dict[str, Any]:
        # Only one profile today — accept and ignore.
        return {"ok": True}

    # ── logs ──────────────────────────────────────────────────────────────────

    def get_logs(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._logs if e["seq"] > since]

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

    def set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if isinstance(patch, dict):
                for k, v in patch.items():
                    if k in self._settings:
                        self._settings[k] = v
            snapshot = dict(self._settings)
            try:
                _save_settings(snapshot)
            except OSError as exc:
                log.warning("could not persist settings: %s", exc)
        self._emit("settings", snapshot)
        return {"ok": True, "settings": snapshot}

    # ── stats ─────────────────────────────────────────────────────────────────

    def _start_stats_loop(self) -> None:
        if self._stats_thread is not None and self._stats_thread.is_alive():
            return
        self._stats_stop.clear()

        def _loop() -> None:
            # The real backend doesn't yet expose per-second throughput. Emit
            # zeros at 1Hz so the UI's live charts have a heartbeat; the values
            # will become real once tunnel.py grows a stats hook.
            while not self._stats_stop.is_set():
                self._emit("stats", dict(self._stats))
                time.sleep(1.0)

        self._stats_thread = threading.Thread(
            target=_loop, daemon=True, name="outwarp-stats"
        )
        self._stats_thread.start()

    def _stop_stats_loop(self) -> None:
        self._stats_stop.set()
        self._stats_thread = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._stop_stats_loop()
        if self._manager is not None:
            try:
                self._manager.stop()
            except Exception:
                log.exception("manager.stop failed during shutdown")
