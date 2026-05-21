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
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from outwarp_server.binaries import find_wg, find_wstunnel
from outwarp_server.config import (
    ServerConfig,
    default_config_dir,
    default_config_path,
)
from outwarp_server.crypto import generate_tls_cert, generate_wg_keypair
from outwarp_server.logs import MemoryLogHandler
from outwarp_server.platforms import get_server_platform
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
        "cli_on_path": False,
    }


def _cli_dir() -> Path | None:
    """Directory holding outwarp-server.exe — only meaningful in a frozen
    install, where the CLI exe sits next to the GUI exe ({app}\\server)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _paths_equal(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    except Exception:
        return a == b


def _read_user_path() -> tuple[list[str], int]:
    """Return (entries, value_type) from HKCU\\Environment\\Path.

    Missing value -> ([], REG_EXPAND_SZ). Reading the *user* hive (not the
    expanded process PATH) is what lets us edit it without clobbering machine
    entries or needing admin.
    """
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
        try:
            value, vtype = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return [], winreg.REG_EXPAND_SZ
    return [e for e in str(value).split(";") if e], vtype


def _write_user_path(entries: list[str], vtype: int) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, vtype or winreg.REG_EXPAND_SZ, ";".join(entries))
    _broadcast_env_change()


_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002


def _broadcast_env_change() -> None:
    """Tell already-open shells the environment changed so new terminals pick
    up the edited PATH without a logoff."""
    try:
        import ctypes
        result = ctypes.c_long()
        ctypes.windll.user32.SendMessageTimeoutW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0,
            ctypes.c_wchar_p("Environment"), _SMTO_ABORTIFHUNG, 5000,
            ctypes.byref(result),
        )
    except Exception:
        log.debug("WM_SETTINGCHANGE broadcast failed", exc_info=True)


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
        """Called once after the window is created so we can push events to JS."""
        # Backfill the log buffer *before* publishing the window — _record_log
        # is a no-op for _emit() while window is None, so we don't waste time
        # calling evaluate_js on a renderer that hasn't started yet
        # (webview.start() runs after this and is what actually boots it). The
        # UI picks the backfill up on first paint via api.get_logs(0); the
        # watcher below covers everything after.
        for line in self._memory_handler.snapshot():
            self._record_log("info", line)
        self._window = window
        self._start_log_watcher()

    def notify_ready(self) -> dict[str, Any]:
        """Called by the JS shell once the page is fully mounted and ready to receive events.

        Starts the live poll so events are never dispatched before the React
        tree has attached its window.addEventListener listeners.
        """
        self._start_live_poll()
        return {"ok": True}

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
        ws, wg = find_wstunnel(), find_wg()
        return {"wstunnel": str(ws) if ws else None, "wg": str(wg) if wg else None}

    def detect_public_ip(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
                return {"ip": r.read().decode().strip()}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ip": None, "error": str(exc)}

    def get_app_info(self) -> dict[str, Any]:
        import platform as _platform
        import sys as _sys

        from outwarp_server import __version__
        return {
            "version": __version__,
            "python": _sys.version.split()[0],
            "platform": _platform.platform(),
            "repo_url": "https://github.com/fcrespo07/OutWarp",
            "license": "MIT",
            "third_party": [
                {"name": "wstunnel",  "license": "BSD-3-Clause",
                 "url": "https://github.com/erebe/wstunnel"},
                {"name": "WireGuard", "license": "GPL-2.0",
                 "url": "https://www.wireguard.com/"},
                {"name": "pywebview", "license": "BSD-3-Clause",
                 "url": "https://pywebview.flowrl.com/"},
                {"name": "rich",      "license": "MIT",
                 "url": "https://github.com/Textualize/rich"},
                {"name": "cryptography", "license": "Apache-2.0 / BSD-3-Clause",
                 "url": "https://cryptography.io/"},
            ],
        }

    def open_url(self, url: str) -> dict[str, Any]:
        import webbrowser
        try:
            webbrowser.open(url, new=2)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_diagnostics(self) -> dict[str, Any]:
        """Run the full diagnostics battery and return a JSON-serialisable report.

        Returns {"ok": bool, "checks": [...], "summary": {...}} so the UI can
        render the table and a one-line headline. The blocking checks (network
        egress, PowerShell calls) can take a few seconds; the JS side awaits.
        """
        if self._manager is None:
            return {
                "ok": False,
                "error": "Server not configured yet — run setup first.",
                "checks": [],
                "summary": {"pass": 0, "warn": 0, "fail": 1, "skip": 0},
            }

        from outwarp_server.diagnostics import Status, run_all

        results = run_all(self._manager.config)
        checks = [
            {
                "name": r.name,
                "status": r.status.value,
                "detail": r.detail,
                "remediation": r.remediation,
                "remediation_command": r.remediation_command,
            }
            for r in results
        ]
        summary = {s.value: 0 for s in Status}
        for r in results:
            summary[r.status.value] += 1
        return {
            "ok": summary["fail"] == 0,
            "checks": checks,
            "summary": summary,
        }

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
            from outwarp_server.platforms import get_server_platform
            iface = get_server_platform().wg_interface_name()
            live = get_live_peers(iface)
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

    def save_owcfg(self, name: str, content_base64: str) -> dict[str, Any]:
        """Open a native SAVE_DIALOG and write the .owcfg there.

        HTML5 <a download="..."> doesn't reliably trigger a file save in
        pywebview (WebView2/WebKit handle the download attribute differently
        than a real browser), so we route through the bridge instead.
        """
        if self._window is None:
            return {"ok": False, "error": "no window"}
        try:
            content = base64.b64decode(content_base64)
        except Exception as exc:
            return {"ok": False, "error": f"invalid content: {exc}"}

        downloads = Path.home() / "Downloads"
        if not downloads.is_dir():
            downloads = Path.home()

        try:
            import webview
            chosen = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(downloads),
                save_filename=f"{name}.owcfg",
            )
        except Exception as exc:
            log.exception("save_owcfg: dialog failed")
            return {"ok": False, "error": f"dialog failed: {exc}"}

        if not chosen:
            return {"ok": False, "error": "cancelled"}
        # pywebview returns str for SAVE_DIALOG in some versions and
        # tuple[str, ...] in others — accept both.
        path = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
        if not path:
            return {"ok": False, "error": "cancelled"}

        try:
            Path(path).write_bytes(content)
        except OSError as exc:
            return {"ok": False, "error": f"could not write: {exc}"}
        return {"ok": True, "path": path}

    def get_client(self, name: str) -> dict[str, Any]:
        """Extended client info: list_clients() row + public key + allowed IPs."""
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        rows = self.list_clients()
        row = next((r for r in rows if r["name"] == name), None)
        if row is None:
            return {"ok": False, "error": "client not found"}
        entry = next((c for c in self._manager.config.clients if c.name == name), None)
        allowed = [f"{entry.address.split('/')[0]}/32"] if entry else []
        return {"ok": True, **row, "allowed_ips": allowed}

    def regenerate_owcfg(self, name: str) -> dict[str, Any]:
        """Rewrite a client's .owcfg.

        The server doesn't keep the client's private key, so a true "rebuild"
        is cryptographically impossible — this rotates keys under the hood
        and returns the new file. The UI must warn the user that the old
        .owcfg is invalidated; the confirm prompt is identical to rotate.
        """
        return self.rotate_client_keys(name)

    def rotate_client_keys(self, name: str) -> dict[str, Any]:
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        try:
            owcfg_path, new_public = self._manager.rotate_client_keys(name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("rotate_client_keys failed")
            return {"ok": False, "error": str(exc)}
        try:
            owcfg_bytes = owcfg_path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"could not read generated owcfg: {exc}"}
        self._emit("clients", self.list_clients())
        return {
            "ok": True,
            "name": name,
            "path": str(owcfg_path),
            "public_key": new_public,
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

    def _emit_setup(self, phase: str, status: str, message: str = "") -> None:
        self._emit("setup_progress", {"phase": phase, "status": status, "message": message})

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

        # Phase: deps
        self._emit_setup("deps", "running")
        wstunnel_bin = find_wstunnel()
        wg_bin = find_wg()
        if not wstunnel_bin or not wg_bin:
            missing = ", ".join(n for n, v in (("wstunnel", wstunnel_bin), ("wg", wg_bin)) if not v)
            self._emit_setup("deps", "fail", missing)
            err = f"missing dependencies: {missing}"
            self._emit("setup_done", {"ok": False, "error": err})
            return {"ok": False, "error": err}
        self._emit_setup("deps", "ok", f"wstunnel={wstunnel_bin}, wg={wg_bin}")

        # Phase: cert
        self._emit_setup("cert", "running")
        cfg_dir = default_config_dir()
        try:
            import secrets
            upgrade_path = secrets.token_urlsafe(32)
            cert_path, key_path, fingerprint = generate_tls_cert(endpoint, cfg_dir / "tls")
            wg_priv, wg_pub = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
        except Exception as exc:
            log.exception("setup: crypto generation failed")
            self._emit_setup("cert", "fail", str(exc))
            self._emit("setup_done", {"ok": False, "error": f"crypto: {exc}"})
            return {"ok": False, "error": f"crypto: {exc}"}
        self._emit_setup("cert", "ok", fingerprint)

        # Phase: systemd (write config to disk + replace manager — the actual
        # service install happens later when the user clicks Start)
        self._emit_setup("systemd", "running")
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
            self._emit_setup("systemd", "fail", str(exc))
            self._emit("setup_done", {"ok": False, "error": f"could not save config: {exc}"})
            return {"ok": False, "error": f"could not save config: {exc}"}

        new_manager = ServerManager(new_config)
        new_manager.add_listener(self._on_state_change)
        self._manager = new_manager
        if self._on_manager_replaced is not None:
            try:
                self._on_manager_replaced(new_manager)
            except Exception:
                log.exception("on_manager_replaced raised")
        self._emit_setup("systemd", "ok", str(default_config_path()))

        # Phase: probe — runs in background so the wizard can complete quickly.
        # The external check can take up to 10s; gating setup on it would mean
        # the user sees a spinner that long, and an unreachable port shouldn't
        # block configuration (the service is still installed correctly).
        self._emit_setup("probe", "running")
        threading.Thread(
            target=self._run_setup_probe, daemon=True, name="outwarp-setup-probe",
        ).start()

        self._emit_setup("done", "ok")
        self._emit("setup_done", {"ok": True, "fingerprint": fingerprint})
        return {"ok": True, "fingerprint": fingerprint}

    def _run_setup_probe(self) -> None:
        try:
            probe = self.probe_external_port()
            if probe.get("reachable"):
                self._emit_setup("probe", "ok", probe.get("detail", ""))
            else:
                self._emit_setup("probe", "warn", probe.get("detail", "unreachable"))
        except Exception as exc:
            self._emit_setup("probe", "warn", str(exc))

    def _bounce_wstunnel(self, port_changed: bool = False) -> None:
        """Restart whichever wstunnel is actually serving traffic.

        In headless deployments wstunnel runs under systemd
        (LinuxServerPlatform.install_wstunnel_service); in GUI dev mode it's a
        subprocess managed by ServerManager. We restart whichever applies so
        the user's change takes effect regardless of how the server was set up.

        port_changed=True triggers a full systemd unit rewrite (the ExecStart
        line bakes in the port, so a plain `systemctl restart` would re-bind
        to the old port).
        """
        platform = get_server_platform()
        cfg = self._manager.config if self._manager else None

        try:
            if platform.is_wstunnel_running():
                if port_changed:
                    wstunnel_bin = find_wstunnel()
                    if wstunnel_bin and cfg is not None:
                        # Rewrite the unit so ExecStart points at the new port,
                        # then explicitly restart — `enable --now` does NOT
                        # apply a new ExecStart to an already-running service.
                        platform.install_wstunnel_service(
                            port=cfg.port,
                            cert_path=Path(cfg.cert_path),
                            key_path=Path(cfg.key_path),
                            upgrade_path=cfg.http_upgrade_path_prefix,
                            wg_listen_port=cfg.wg_listen_port,
                            wstunnel_bin=Path(wstunnel_bin),
                        )
                platform.restart_wstunnel_service()
        except Exception:
            log.exception("_bounce_wstunnel: systemd path failed")

        try:
            if self._manager is not None and self._manager._wstunnel is not None:  # noqa: SLF001
                self._manager.restart()
        except Exception:
            log.exception("_bounce_wstunnel: subprocess path failed")

    def update_server_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Update editable server fields (port, wg_listen_port, endpoint) and restart.

        Any field omitted from the patch stays unchanged. After persisting the
        new config the service is restarted so wstunnel re-binds to the new
        port / endpoint. Existing client .owcfg files keep working only if
        their pinned endpoint remains reachable.
        """
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        cfg = self._manager.config

        new_port = cfg.port
        new_wg_port = cfg.wg_listen_port
        new_endpoint = cfg.endpoint

        if "port" in patch:
            try:
                new_port = int(patch["port"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "invalid port"}
            if not (1 <= new_port <= 65535):
                return {"ok": False, "error": "port out of range"}
        if "wg_listen_port" in patch:
            try:
                new_wg_port = int(patch["wg_listen_port"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "invalid wg_listen_port"}
            if not (1 <= new_wg_port <= 65535):
                return {"ok": False, "error": "wg_listen_port out of range"}
        if "endpoint" in patch:
            ep = str(patch["endpoint"] or "").strip()
            if not ep:
                return {"ok": False, "error": "endpoint required"}
            new_endpoint = ep

        from dataclasses import replace as _replace
        new_cfg = _replace(cfg, port=new_port, wg_listen_port=new_wg_port, endpoint=new_endpoint)
        try:
            from outwarp_server.config import default_config_path as _path
            new_cfg.save(_path())
        except OSError as exc:
            return {"ok": False, "error": f"could not save config: {exc}"}

        wss_port_changed = new_cfg.port != cfg.port
        wg_port_changed = new_cfg.wg_listen_port != cfg.wg_listen_port

        if wss_port_changed:
            log.warning(
                "WSS port changed %d → %d. Remember to open the new port in "
                "ufw / iptables / cloud firewall — this code does not touch "
                "the firewall.",
                cfg.port, new_cfg.port,
            )

        self._manager._config = new_cfg  # noqa: SLF001 (intentional poke)

        def _bounce() -> None:
            # 1) Restart wstunnel (systemd unit rewrite if WSS port changed,
            #    plain restart otherwise; also bounce the GUI subprocess).
            self._bounce_wstunnel(port_changed=wss_port_changed)

            # 2) WG: install_wg_config does syncconf for peer changes, but
            #    syncconf cannot change ListenPort or replay PostUp/PostDown.
            #    Force a full down/up when the WG port (or subnet — handled
            #    by future patches) really has to change.
            platform = get_server_platform()
            try:
                if wg_port_changed and platform.is_wg_active():
                    platform.restart_wg()
                else:
                    from outwarp_server.server_manager import _get_wg_conf
                    platform.install_wg_config(_get_wg_conf(new_cfg))
            except Exception:
                log.exception("update_server_config: wg bounce failed")

        threading.Thread(target=_bounce, daemon=True, name="api-cfg-update").start()
        self._emit("status", {
            "status": _STATE_TO_JS.get(self._manager.state, "stopped"),
            "config_present": True,
        })
        return {"ok": True}

    def rotate_tls_cert(self) -> dict[str, Any]:
        """Regenerate the self-signed TLS certificate and restart wstunnel.

        Every .owcfg already distributed pins the OLD fingerprint and will
        stop validating until clients re-import the new one. UI must warn.
        """
        if self._manager is None:
            return {"ok": False, "error": "server not configured"}
        cfg = self._manager.config
        try:
            cert_dir = Path(cfg.cert_path).parent
            cert_path, key_path, fingerprint = generate_tls_cert(cfg.endpoint, cert_dir)
        except Exception as exc:
            log.exception("rotate_tls_cert: cert generation failed")
            return {"ok": False, "error": str(exc)}

        from dataclasses import replace as _replace
        new_cfg = _replace(
            cfg,
            cert_path=str(cert_path),
            key_path=str(key_path),
            cert_fingerprint_sha256=fingerprint,
        )
        try:
            from outwarp_server.config import default_config_path as _path
            new_cfg.save(_path())
        except OSError as exc:
            return {"ok": False, "error": f"could not save config: {exc}"}

        self._manager._config = new_cfg  # noqa: SLF001

        def _bounce() -> None:
            # Cert files were overwritten in place, so the systemd ExecStart
            # path still points at the right files — a plain restart is enough.
            self._bounce_wstunnel(port_changed=False)

        threading.Thread(target=_bounce, daemon=True, name="api-cert-rotate").start()
        self._emit("status", {
            "status": _STATE_TO_JS.get(self._manager.state, "stopped"),
            "config_present": True,
            "cert_fingerprint_sha256": fingerprint,
        })
        return {"ok": True, "fingerprint": fingerprint}

    def probe_external_port(self) -> dict[str, Any]:
        """Probe whether the configured WSS port is reachable from the public internet.

        Uses ifconfig.co's /port/<n> endpoint, which initiates a TCP connect back
        to the source IP from a third-party host. Returns reachable=False with
        detail on any failure — a transient false negative shouldn't be alarming.
        """
        if self._manager is None:
            return {"ok": False, "reachable": False, "detail": "server not configured"}
        cfg = self._manager.config
        port = cfg.port
        host = cfg.endpoint
        try:
            req = urllib.request.Request(
                f"https://ifconfig.co/port/{port}",
                headers={"Accept": "application/json", "User-Agent": "outwarp-server"},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            reachable = bool(body.get("reachable"))
            return {
                "ok": True,
                "reachable": reachable,
                "detail": f"{host}:{port} → {'reachable' if reachable else 'closed/blocked'}",
            }
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            return {"ok": False, "reachable": False, "detail": str(exc)}

    # ── logs ─────────────────────────────────────────────────────────────────

    def get_logs(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._logs if e["seq"] > since]

    def clear_logs(self) -> dict[str, Any]:
        with self._lock:
            self._logs.clear()
        return {"ok": True}

    def export_logs(self) -> dict[str, Any]:
        """Write the current in-memory log buffer to a file the user picks
        via the native save dialog.

        pywebview's create_file_dialog on Windows can refuse to open the
        dialog when called without a starting directory, so we mirror
        save_owcfg and pass one explicitly.
        """
        if self._window is None:
            log.warning("export_logs called before window was bound")
            return {"ok": False, "error": "no window"}

        downloads = Path.home() / "Downloads"
        if not downloads.is_dir():
            downloads = Path.home()

        try:
            import webview
            chosen = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(downloads),
                save_filename="outwarp-server-logs.txt",
            )
        except Exception as exc:
            log.exception("export_logs: file dialog failed")
            return {"ok": False, "error": f"dialog failed: {exc}"}

        if not chosen:
            return {"ok": False, "error": "cancelled"}
        path = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
        if not path:
            return {"ok": False, "error": "cancelled"}

        try:
            with self._lock:
                lines = [
                    f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts']))} "
                    f"[{e['level'].upper()}] {e['msg']}"
                    for e in self._logs
                ]
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            log.exception("export_logs: write failed")
            return {"ok": False, "error": f"could not write: {exc}"}
        return {"ok": True, "path": path}

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

    # ── console CLI activation ────────────────────────────────────────────────

    def get_cli_status(self) -> dict[str, Any]:
        """Report whether the console CLI can be / is exposed on the user PATH.

        supported  — running on Windows (the toggle only makes sense there)
        available  — the outwarp-server.exe console build exists on disk
        enabled    — its directory is currently on the user's PATH
        """
        if sys.platform != "win32":
            return {"supported": False, "available": False, "enabled": False, "cli_dir": None}
        cdir = _cli_dir()
        exe = (cdir / "outwarp-server.exe") if cdir else None
        available = bool(exe and exe.exists())
        enabled = False
        if available:
            try:
                entries, _ = _read_user_path()
                enabled = any(_paths_equal(e, str(cdir)) for e in entries)
            except OSError:
                log.exception("get_cli_status: could not read user PATH")
        return {
            "supported": True,
            "available": available,
            "enabled": enabled,
            "cli_dir": str(cdir) if cdir else None,
        }

    def set_cli_enabled(self, enabled: bool) -> dict[str, Any]:
        if sys.platform != "win32":
            return {"ok": False, "error": "only supported on Windows"}
        cdir = _cli_dir()
        if cdir is None or not (cdir / "outwarp-server.exe").exists():
            return {"ok": False, "error": "CLI executable not found in this build"}
        target = str(cdir)
        try:
            entries, vtype = _read_user_path()
            present = any(_paths_equal(e, target) for e in entries)
            if enabled and not present:
                entries.append(target)
                _write_user_path(entries, vtype)
            elif not enabled and present:
                entries = [e for e in entries if not _paths_equal(e, target)]
                _write_user_path(entries, vtype)
        except OSError as exc:
            log.exception("set_cli_enabled failed")
            return {"ok": False, "error": str(exc)}

        with self._lock:
            self._settings["cli_on_path"] = bool(enabled)
            snapshot = dict(self._settings)
        _save_settings(snapshot)
        self._emit("settings", snapshot)
        return {"ok": True, "enabled": bool(enabled), "cli_dir": target}

    # ── lifecycle ────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._poll_stop.set()
        if self._manager is not None:
            try:
                self._manager.stop()
            except Exception:
                log.exception("manager.stop failed during shutdown")
