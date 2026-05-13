"""
JS <-> Python bridge for the OutWarp server GUI.

Methods on `Api` are exposed to the renderer as ``window.pywebview.api.<method>``.
The UI in ``ui/`` calls them; the server backend in ``server_manager.py`` is the
only thing that actually touches systemd, wg-quick or wstunnel.

Python -> JS uses ``_emit(name, payload)`` which fires a ``CustomEvent`` named
``outwarp:<name>`` on the window object.

Events fired:
  outwarp:status   -> service state changed
  outwarp:clients  -> client list changed (someone added/revoked)
  outwarp:log      -> a single log line was emitted
  outwarp:settings -> persisted GUI preferences changed
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from outwarp_server.config import (
    ServerConfig,
    default_config_dir,
    default_config_path,
)
from outwarp_server.crypto import generate_tls_cert, generate_wg_keypair
from outwarp_server.logs import MemoryLogHandler
from outwarp_server.server_manager import ServerManager, ServerState
from outwarp_server.wireguard import get_live_peers

log = logging.getLogger(__name__)

_STATE_TO_JS = {
    ServerState.STOPPED:  "stopped",
    ServerState.STARTING: "starting",
    ServerState.RUNNING:  "running",
    ServerState.ERROR:    "error",
}

_ONLINE_WINDOW_SECONDS = 180


def _settings_path() -> Path:
    return default_config_dir() / "gui_settings.json"


def _default_settings() -> dict[str, Any]:
    return {
        "language": "es",
        "theme": "auto",
        "advanced": False,
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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("could not persist GUI settings: %s", exc)


class Api:
    def __init__(
        self,
        memory_handler: MemoryLogHandler,
        manager: ServerManager | None,
        on_manager_replaced: Callable[[ServerManager], None] | None = None,
    ) -> None:
        self._window: Any = None
        self._memory_handler = memory_handler
        self._manager: ServerManager | None = manager
        self._on_manager_replaced = on_manager_replaced

        self._lock = threading.Lock()
        self._settings = _load_settings()
        self._log_seq = 0
        self._logs: deque[dict[str, Any]] = deque(maxlen=2000)
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if manager is not None:
            manager.add_listener(self._on_state_change)

    # ── pywebview wiring ──────────────────────────────────────────────────────

    def bind_window(self, window: Any) -> None:
        self._window = window
        for line in self._memory_handler.snapshot():
            self._record_log("info", line)
        self._start_log_watcher()
        self._start_live_poll()

    def _start_live_poll(self) -> None:
        """Re-emit status + client list every 2s.

        wg handshakes happen at the kernel level and never fire a Python
        callback — without this poll the UI's "online/offline" pill for each
        client would stay frozen until the next add/revoke. The status
        heartbeat also acts as a safety net for any evaluate_js call the
        webview dropped during page load.
        """
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()

        def _loop() -> None:
            while not self._poll_stop.is_set():
                try:
                    if self._manager is not None:
                        self._emit("status", {
                            "status": _STATE_TO_JS.get(self._manager.state, "stopped"),
                            "config_present": True,
                        })
                        self._emit("clients", self.list_clients())
                except Exception:
                    log.exception("live poll iteration failed")
                self._poll_stop.wait(2.0)

        self._poll_thread = threading.Thread(
            target=_loop, daemon=True, name="outwarp-server-poll",
        )
        self._poll_thread.start()

    def _emit(self, name: str, payload: Any) -> None:
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

    # ── status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        if self._manager is None:
            return {"status": "empty", "config_present": False}
        cfg = self._manager.config
        return {
            "status": _STATE_TO_JS.get(self._manager.state, "stopped"),
            "config_present": True,
            "endpoint": cfg.endpoint,
            "port": cfg.port,
            "subnet": cfg.subnet,
            "server_address": cfg.server_address,
            "wg_listen_port": cfg.wg_listen_port,
            "cert_fingerprint_sha256": cfg.cert_fingerprint_sha256,
            "clients_count": len(cfg.clients),
        }

    def get_deps(self) -> dict[str, str | None]:
        return {"wstunnel": shutil.which("wstunnel"), "wg": shutil.which("wg")}

    def detect_public_ip(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
                return {"ip": r.read().decode().strip()}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ip": None, "error": str(exc)}

    def _on_state_change(self, state: ServerState) -> None:
        self._emit("status", {
            "status": _STATE_TO_JS.get(state, "stopped"),
            "config_present": self._manager is not None,
        })

    # ── service control ──────────────────────────────────────────────────────

    def start_service(self) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        self._manager.start()
        return {"ok": True}

    def stop_service(self) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        threading.Thread(
            target=self._manager.stop, daemon=True, name="api-stop"
        ).start()
        return {"ok": True}

    def restart_service(self) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        threading.Thread(
            target=self._manager.restart, daemon=True, name="api-restart"
        ).start()
        return {"ok": True}

    # ── clients ──────────────────────────────────────────────────────────────

    def list_clients(self) -> list[dict[str, Any]]:
        if self._manager is None:
            return []
        try:
            live = get_live_peers()
        except Exception:
            live = {}
        now = int(time.time())
        out = []
        for c in self._manager.config.clients:
            peer = live.get(c.public_key)
            if peer is None:
                status_, age = "unknown", None
                endpoint = None
                rx = tx = 0
            elif peer.latest_handshake is None:
                status_, age = "idle", None
                endpoint = peer.endpoint
                rx, tx = peer.transfer_rx, peer.transfer_tx
            else:
                age = now - peer.latest_handshake
                status_ = "online" if age < _ONLINE_WINDOW_SECONDS else "offline"
                endpoint = peer.endpoint
                rx, tx = peer.transfer_rx, peer.transfer_tx
            out.append({
                "name": c.name,
                "address": c.address,
                "public_key": c.public_key,
                "status": status_,
                "last_handshake_seconds_ago": age,
                "endpoint": endpoint,
                "rx_bytes": rx,
                "tx_bytes": tx,
            })
        return out

    def add_client(self, name: str) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "name is required"}
        try:
            owcfg_path = self._manager.add_client(name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("add_client failed")
            return {"ok": False, "error": str(exc)}
        try:
            owcfg_bytes = owcfg_path.read_bytes()
            owcfg_text = owcfg_bytes.decode("utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"could not read generated owcfg: {exc}"}
        self._emit("clients", self.list_clients())
        return {
            "ok": True,
            "name": name,
            "path": str(owcfg_path),
            "owcfg": owcfg_text,
            "owcfg_base64": base64.b64encode(owcfg_bytes).decode("ascii"),
        }

    def revoke_client(self, name: str) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        try:
            self._manager.revoke_client(name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self._emit("clients", self.list_clients())
        return {"ok": True}

    # ── setup wizard ─────────────────────────────────────────────────────────

    def run_setup(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._manager is not None:
            return {"ok": False, "error": "server already configured"}

        try:
            endpoint = (payload.get("endpoint") or "").strip()
            if not endpoint:
                return {"ok": False, "error": "endpoint is required"}
            port = int(payload.get("port", 443))
            wg_listen_port = int(payload.get("wg_listen_port", 51820))
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid port"}

        for label, value in (("port", port), ("wg_listen_port", wg_listen_port)):
            if not (1 <= value <= 65535):
                return {"ok": False, "error": f"{label} out of range"}

        subnet = (payload.get("subnet") or "10.0.0.0/24").strip()
        server_address = (
            payload.get("server_address")
            or f"{subnet.split('/')[0].rsplit('.', 1)[0]}.1/24"
        ).strip()

        cfg_dir = default_config_dir()
        try:
            import secrets
            upgrade_path = secrets.token_urlsafe(32)
            cert_path, key_path, fingerprint = generate_tls_cert(endpoint, cfg_dir / "tls")
            wg_bin = shutil.which("wg")
            wg_priv, wg_pub = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
        except Exception as exc:
            log.exception("setup: crypto generation failed")
            return {"ok": False, "error": f"crypto: {exc}"}

        new_config = ServerConfig(
            schema_version=1,
            endpoint=endpoint,
            port=port,
            http_upgrade_path_prefix=upgrade_path,
            cert_path=str(cert_path),
            key_path=str(key_path),
            cert_fingerprint_sha256=fingerprint,
            wg_private_key=wg_priv,
            wg_public_key=wg_pub,
            subnet=subnet,
            server_address=server_address,
            wg_listen_port=wg_listen_port,
            clients=[],
        )
        try:
            new_config.save(default_config_path())
        except OSError as exc:
            return {"ok": False, "error": f"could not save config: {exc}"}

        new_manager = ServerManager(new_config)
        new_manager.add_listener(self._on_state_change)
        self._manager = new_manager
        if self._on_manager_replaced is not None:
            try:
                self._on_manager_replaced(new_manager)
            except Exception:
                log.exception("on_manager_replaced raised")

        return {"ok": True, "fingerprint": fingerprint}

    # ── logs ─────────────────────────────────────────────────────────────────

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
        last_count = len(self._memory_handler.snapshot())

        def _loop() -> None:
            nonlocal last_count
            while True:
                snap = self._memory_handler.snapshot()
                if len(snap) < last_count:
                    last_count = 0
                if len(snap) > last_count:
                    for line in snap[last_count:]:
                        level = "info"
                        for token in ("ERROR", "WARNING", "DEBUG"):
                            if f"[{token}]" in line:
                                level = token.lower().replace("warning", "warn")
                                break
                        self._record_log(level, line)
                    last_count = len(snap)
                time.sleep(0.25)

        threading.Thread(target=_loop, daemon=True, name="outwarp-log-watcher").start()

    # ── settings ─────────────────────────────────────────────────────────────

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
        _save_settings(snapshot)
        self._emit("settings", snapshot)
        return {"ok": True, "settings": snapshot}

    # ── lifecycle ────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._poll_stop.set()
        if self._manager is not None:
            try:
                self._manager.stop()
            except Exception:
                log.exception("manager.stop failed during shutdown")
