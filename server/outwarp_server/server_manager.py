from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from enum import Enum
from pathlib import Path

from outwarp_server.binaries import find_wg
from outwarp_server.config import ClientEntry, ServerConfig, default_config_path
from outwarp_server.crypto import generate_psk, generate_wg_keypair
from outwarp_server.ip_pool import PoolExhaustedError, next_available_ip
from outwarp_server.owcfg import build_owcfg, write_owcfg
from outwarp_server.platforms import PlatformError, get_server_platform
from outwarp_server.wireguard import (
    add_peer_live,
    build_server_wg_conf,
    remove_peer_live,
)

log = logging.getLogger(__name__)

# A client name doubles as a config identifier and the <name>.owcfg filename
# written to the cwd. Without this an unsanitised name like '../x' or 'a/b'
# would escape the directory or fail mid-write. Allow a conservative charset
# only; reject path separators, traversal and control characters.
_CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")


def validate_client_name(name: str) -> str:
    """Return the stripped name if it is a safe identifier, else raise ValueError."""
    if not isinstance(name, str):
        raise ValueError("Client name must be text")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Client name is required")
    if cleaned in (".", ".."):
        raise ValueError("Invalid client name")
    if not _CLIENT_NAME_RE.match(cleaned):
        raise ValueError(
            "Client name may only contain letters, digits, spaces, '.', '_' and "
            "'-' (1-64 characters, not starting with a separator)"
        )
    return cleaned

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_MONITOR_INTERVAL = 5.0


def _find_wstunnel() -> str | None:
    """Locate wstunnel: bundled next to the frozen .exe (or one level up, the
    shared install root the installer drops it in) before the system PATH."""
    from outwarp_server.binaries import find_wstunnel
    found = find_wstunnel()
    return str(found) if found else None


class ServerState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


def _build_wstunnel_command(config: ServerConfig, wstunnel_bin: Path) -> list[str]:
    return [
        str(wstunnel_bin),
        "server",
        "--restrict-to", f"127.0.0.1:{config.wg_listen_port}",
        "--tls-certificate", config.cert_path,
        "--tls-private-key", config.key_path,
        "--restrict-http-upgrade-path-prefix", config.http_upgrade_path_prefix,
        f"wss://0.0.0.0:{config.port}",
    ]


def _get_wg_conf(config: ServerConfig) -> str:
    if sys.platform == "win32":
        from outwarp_server.wireguard import build_server_wg_conf_windows
        return build_server_wg_conf_windows(config)
    return build_server_wg_conf(config)


class ServerManager:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._state = ServerState.STOPPED
        self._wstunnel: subprocess.Popen | None = None
        self._listeners: list[Callable[[ServerState], None]] = []
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # Traffic-history scheduler lives for the duration of the run; the TUI
        # dashboard reads its DB to render the 24h sparkline + top talkers.
        self._traffic_scheduler = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def config(self) -> ServerConfig:
        return self._config

    def add_listener(self, fn: Callable[[ServerState], None]) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        with self._lock:
            if self._state in (ServerState.STARTING, ServerState.RUNNING):
                return
            self._set_state(ServerState.STARTING)
        threading.Thread(target=self._do_start, daemon=True, name="server-start").start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None

        if self._traffic_scheduler is not None:
            try:
                self._traffic_scheduler.stop()
            except Exception:
                log.exception("Error stopping traffic scheduler")
            self._traffic_scheduler = None

        proc = self._wstunnel
        if proc is not None:
            self._wstunnel = None
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            except Exception:
                log.exception("Error stopping wstunnel")
            log.info("wstunnel stopped")

        try:
            get_server_platform().uninstall_wg_config()
            log.info("WireGuard server interface stopped")
        except PlatformError as exc:
            log.warning("Could not stop WireGuard: %s", exc)

        self._set_state(ServerState.STOPPED)

    def restart(self) -> None:
        self.stop()
        self._stop_event.clear()
        self.start()

    def add_client(self, name: str, *, expires_at: str = "") -> Path:
        """Generate a new client, update server config, return path to .owcfg.

        `expires_at` is an optional ISO date (YYYY-MM-DD); the client refuses an
        expired profile and `prune_expired` can revoke it server-side.
        """
        name = validate_client_name(name)
        config = self._config

        for c in config.clients:
            if c.name == name:
                raise ValueError(f"Client '{name}' already exists")

        wg_bin = find_wg()
        private_key, public_key = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
        try:
            psk = generate_psk(Path(wg_bin) if wg_bin else None)
        except Exception as exc:
            log.warning("Could not generate preshared key (continuing without one): %s", exc)
            psk = ""

        allocated = [c.address for c in config.clients]
        try:
            client_address = next_available_ip(config.subnet, config.server_address, allocated)
        except PoolExhaustedError as exc:
            raise ValueError(str(exc)) from exc

        try:
            add_peer_live(public_key, client_address, psk=psk)
        except Exception as exc:
            log.warning("Could not hot-add peer (WireGuard may not be running): %s", exc)

        new_client = ClientEntry(
            name=name, public_key=public_key, address=client_address,
            psk=psk, expires_at=expires_at,
        )
        updated = replace(config, clients=[*config.clients, new_client])
        updated.save(default_config_path())
        self._config = updated

        # Persist updated WG config (hot-reload or full restart)
        try:
            get_server_platform().install_wg_config(_get_wg_conf(updated))
        except PlatformError as exc:
            log.warning("Could not persist WG config: %s", exc)

        warpcfg = build_owcfg(
            config, name, private_key, client_address,
            preshared_key=psk, expires_at=expires_at,
        )
        warpcfg_path = Path.cwd() / f"{name}.owcfg"
        write_owcfg(warpcfg, warpcfg_path)
        log.info("Client '%s' added — .owcfg at %s", name, warpcfg_path)
        return warpcfg_path

    def prune_expired(self, *, today: str = "") -> list[str]:
        """Revoke every client whose expires_at is strictly before `today`
        (ISO date, defaults to the current UTC date). Returns the names revoked.
        """
        import datetime

        ref = today or datetime.datetime.now(datetime.UTC).date().isoformat()
        expired = [
            c.name for c in self._config.clients
            if c.expires_at and c.expires_at < ref
        ]
        for name in expired:
            self.revoke_client(name)
        return expired

    def rotate_client_keys(self, name: str) -> tuple[Path, str]:
        """Generate a new WG keypair for an existing client and rewrite its .owcfg.

        The old public key is removed from the peer list; the new one is added.
        Returns (path_to_new_owcfg, new_public_key). The previous .owcfg becomes
        invalid as soon as this returns — the new file must reach the client.
        """
        config = self._config
        target = next((c for c in config.clients if c.name == name), None)
        if target is None:
            raise ValueError(f"Client '{name}' not found")

        wg_bin = find_wg()
        new_private, new_public = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
        try:
            new_psk = generate_psk(Path(wg_bin) if wg_bin else None)
        except Exception as exc:
            log.warning("Could not generate preshared key on rotate: %s", exc)
            new_psk = ""

        try:
            remove_peer_live(target.public_key)
        except Exception as exc:
            log.warning("Could not hot-remove old peer: %s", exc)
        try:
            add_peer_live(new_public, target.address, psk=new_psk)
        except Exception as exc:
            log.warning("Could not hot-add rotated peer: %s", exc)

        updated_clients = [
            ClientEntry(
                name=c.name, public_key=new_public, address=c.address,
                psk=new_psk, expires_at=c.expires_at,
            )
            if c.name == name else c
            for c in config.clients
        ]
        updated = replace(config, clients=updated_clients)
        updated.save(default_config_path())
        self._config = updated

        try:
            get_server_platform().install_wg_config(_get_wg_conf(updated))
        except PlatformError as exc:
            log.warning("Could not persist WG config: %s", exc)

        warpcfg = build_owcfg(
            updated, name, new_private, target.address,
            preshared_key=new_psk, expires_at=target.expires_at,
        )
        warpcfg_path = Path.cwd() / f"{name}.owcfg"
        write_owcfg(warpcfg, warpcfg_path)
        log.info("Client '%s' keys rotated — new .owcfg at %s", name, warpcfg_path)
        return warpcfg_path, new_public

    def revoke_client(self, name: str) -> None:
        config = self._config

        target = next((c for c in config.clients if c.name == name), None)
        if target is None:
            raise ValueError(f"Client '{name}' not found")

        try:
            remove_peer_live(target.public_key)
        except Exception as exc:
            log.warning("Could not hot-remove peer: %s", exc)

        updated = replace(config, clients=[c for c in config.clients if c.name != name])
        updated.save(default_config_path())
        self._config = updated

        try:
            get_server_platform().install_wg_config(_get_wg_conf(updated))
        except PlatformError as exc:
            log.warning("Could not persist WG config: %s", exc)

        log.info("Client '%s' revoked", name)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_state(self, state: ServerState) -> None:
        if state == self._state:
            return
        self._state = state
        log.debug("Server state → %s", state.value)
        for fn in list(self._listeners):
            try:
                fn(state)
            except Exception:
                log.exception("State listener raised")

    def _do_start(self) -> None:
        try:
            platform = get_server_platform()

            # Verify NAT prerequisites (Windows: MSFT_NetNat WMI provider).
            # If we skip this and prepare_system() silently no-ops the NAT
            # creation, the server appears healthy but clients get no return
            # traffic — the failure mode that originally hid behind a
            # log.warning. Fail loudly instead.
            from outwarp_server.platforms.base import PrerequisiteStatus
            prereq = platform.check_prerequisites()
            if prereq.status is not PrerequisiteStatus.OK:
                log.error(
                    "Server cannot start — OS prerequisites not met: %s | %s",
                    prereq.detail, prereq.remediation,
                )
                self._set_state(ServerState.ERROR)
                return

            # OS-level setup (IP forwarding, NAT, firewall). prepare_system()
            # now raises PlatformError if NAT can't be created — propagate it.
            try:
                platform.prepare_system(self._config.subnet, self._config.port)
            except PlatformError as exc:
                log.error("prepare_system failed: %s", exc)
                self._set_state(ServerState.ERROR)
                return

            log.info("Installing WireGuard server interface")
            try:
                platform.install_wg_config(_get_wg_conf(self._config))
            except PlatformError as exc:
                log.error("WireGuard setup failed: %s", exc)
                self._set_state(ServerState.ERROR)
                return

            # `systemctl enable --now wg-quick@wg0` (Linux) and
            # `wireguard.exe /installtunnelservice` (Windows) can both return
            # 0 even when the interface fails to come up — verify explicitly
            # so the GUI shows ERROR instead of a confusingly "running" server
            # whose tunnel handshakes silently never happen.
            wg_iface = platform.wg_interface_name()
            if not platform.is_wg_active(wg_iface):
                log.error(
                    "WireGuard interface '%s' did not come up. On Linux: "
                    "'systemctl status wg-quick@%s' / 'journalctl -u wg-quick@%s -n 50'. "
                    "On Windows: check Service Manager for 'WireGuardTunnel$%s'. "
                    "Common causes: missing wireguard kernel module, config syntax "
                    "error, or PostUp/PostDown script failure.",
                    wg_iface, wg_iface, wg_iface, wg_iface,
                )
                self._set_state(ServerState.ERROR)
                return

            wstunnel_bin = _find_wstunnel()
            if wstunnel_bin is None:
                log.error("wstunnel binary not found in PATH")
                self._set_state(ServerState.ERROR)
                return

            cmd = _build_wstunnel_command(self._config, Path(wstunnel_bin))
            log.info("Starting wstunnel: %s", " ".join(cmd))
            self._wstunnel = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
            threading.Thread(
                target=self._read_output,
                args=(self._wstunnel,),
                daemon=True,
                name="wstunnel-log",
            ).start()

            self._set_state(ServerState.RUNNING)
            log.info("Server running (wstunnel pid=%d)", self._wstunnel.pid)

            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True, name="server-monitor"
            )
            self._monitor_thread.start()

            try:
                from outwarp_server.traffic_history import build_scheduler
                self._traffic_scheduler = build_scheduler(self._config)
                self._traffic_scheduler.start()
            except Exception:
                log.exception("Could not start traffic-history scheduler")

        except Exception:
            log.exception("Unexpected error starting server")
            self._set_state(ServerState.ERROR)

    def _read_output(self, proc: subprocess.Popen) -> None:
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    log.info("[wstunnel] %s", line)
        except Exception:
            pass

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(_MONITOR_INTERVAL):
            if self._state != ServerState.RUNNING:
                break
            proc = self._wstunnel
            if proc is not None and proc.poll() is not None:
                log.error("wstunnel exited unexpectedly (code=%d)", proc.returncode)
                self._set_state(ServerState.ERROR)
                break
