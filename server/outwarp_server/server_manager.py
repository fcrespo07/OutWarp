from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from outwarp_server.config import ServerConfig, default_config_path
from outwarp_server.platforms import PlatformError, get_server_platform
from outwarp_server.wireguard import build_platform_wg_conf

log = logging.getLogger(__name__)

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


def build_wstunnel_command(config: ServerConfig, wstunnel_bin: Path) -> list[str]:
    """The one place the wstunnel server invocation is defined.

    Both the foreground subprocess and the systemd unit's ExecStart render from
    this, because when they were written separately they drifted.

    In the "acme" branch wstunnel drops TLS entirely and binds loopback: Caddy
    owns the public port and the certificate, and is the only thing that ever
    connects here. Binding 127.0.0.1 rather than 0.0.0.0 matters — otherwise the
    plain-WebSocket listener would be reachable from the network directly,
    bypassing the front.

    NOTE: ``http_upgrade_path_prefix`` ends up in /proc/<pid>/cmdline (world-
    readable on most Linux setups). That's intentional: this prefix is a
    *path obfuscation* gate, not an authentication secret. The real auth is
    the TLS-fingerprint pin (client refuses any mismatched cert) plus
    WireGuard's own keypair-based handshake (server only accepts peers that
    ``add-client`` registered). A local attacker who scrapes the prefix from
    cmdline still needs a registered WG keypair before they can do anything
    past the wstunnel front-door — by design, leaking it does not break the
    security model.
    """
    cmd = [
        str(wstunnel_bin),
        "server",
        "--restrict-to", f"127.0.0.1:{config.wg_listen_port}",
        # Enrolment rides the same transport: the client opens a TCP forward to
        # the loopback listener (enroll_server.py) over the very WSS port the
        # tunnel uses, so no second public port is needed. Exactly these two
        # destinations and nothing else — the path prefix gates the upgrade,
        # this gates where a forward may go.
        "--restrict-to", f"127.0.0.1:{config.enroll_port}",
    ]
    if config.behind_reverse_proxy:
        cmd += [
            "--restrict-http-upgrade-path-prefix", config.http_upgrade_path_prefix,
            f"ws://127.0.0.1:{config.internal_ws_port}",
        ]
    else:
        cmd += [
            "--tls-certificate", config.cert_path,
            "--tls-private-key", config.key_path,
            "--restrict-http-upgrade-path-prefix", config.http_upgrade_path_prefix,
            f"wss://0.0.0.0:{config.port}",
        ]
    return cmd


# Kept so existing internal callers and tests that reach for the private name
# keep working; the public one is what new code should use.
_build_wstunnel_command = build_wstunnel_command


def build_enroll_listener_command(config_path: Path) -> list[str]:
    """The one place the standalone enrolment listener invocation is defined.

    Rendered into the systemd unit on Linux (LinuxServerPlatform
    .install_enroll_service), where nothing else keeps the listener alive
    between wizard runs. Resolves the CLI the same way the client's service
    module does: the installed ``outwarp-server`` on PATH first, so a pipx
    install wins over a dev checkout, then whatever launched this process.
    """
    exe = shutil.which("outwarp-server")
    if exe is None:
        exe = str(Path(sys.argv[0]).resolve())
    return [exe, "--config-dir", str(config_path.parent), "enroll-listener"]


def _get_wg_conf(config: ServerConfig) -> str:
    return build_platform_wg_conf(config)


class ServerManager:
    def __init__(self, config: ServerConfig, config_path: Path | None = None) -> None:
        self._config = config
        # Resolved once so a process started with --config-dir keeps reading
        # and writing the same file it was launched with.
        self._config_path = config_path or default_config_path()
        self._state = ServerState.STOPPED
        self._wstunnel: subprocess.Popen | None = None
        self._listeners: list[Callable[[ServerState], None]] = []
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # Traffic-history scheduler lives for the duration of the run; the TUI
        # dashboard reads its DB to render the 24h sparkline + top talkers.
        self._traffic_scheduler = None
        self._enroll_server = None
        self._config_stamp = self._current_config_stamp()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def owns_transport(self) -> bool:
        """True when wstunnel is a subprocess of this manager, i.e. this
        process is the one keeping the tunnel up rather than a companion
        panel next to a `serve` container or a systemd unit."""
        return self._wstunnel is not None

    def _current_config_stamp(self) -> tuple[float, float]:
        """mtimes of the two files another process can change under us."""
        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0
        return (
            _mtime(self._config_path),
            _mtime(self._config_path.parent / "clients.sqlite"),
        )

    def refresh_config(self) -> bool:
        """Reload the config if another process changed it on disk.

        The panel/GUI holds this manager for as long as it runs while the
        state it shows is written by others: the `serve` container's
        enrolment listener admits a client (public key + enrolled_at land in
        clients.sqlite), an admin runs `add-client` over `kubectl exec`, the
        standalone listener on a systemd install redeems a token. Without
        this the panel kept its start-up snapshot forever — a client that
        enrolled minutes ago stayed "pending" and a CLI-added one never
        appeared until the panel was restarted. Cheap enough for the 2 s
        live poll: two stat() calls, and a load only when something moved.
        Returns whether a reload happened.
        """
        stamp = self._current_config_stamp()
        if stamp == self._config_stamp:
            return False
        try:
            self._config = ServerConfig.load(self._config_path)
        except Exception:
            log.exception("Could not reload config after an external change")
            return False
        self._config_stamp = stamp
        return True

    @property
    def effective_state(self) -> ServerState:
        """``state``, reconciled against the OS for a process that never
        started the service itself.

        ``self._state`` only ever changes via this instance's own
        ``start()``/``stop()`` — it defaults to STOPPED and stays there for
        the lifetime of a process that never calls them. That default is
        correct for a lone desktop GUI/TUI/daemon process, but wrong for a
        companion admin surface: the web/GUI panel run alongside a
        separately-managed ``serve`` process (a Docker/Kubernetes sidecar
        container, or a systemd-installed wstunnel unit with no
        continuously-running ``serve`` at all) never calls ``start()``, so
        its dashboard reported "stopped" forever even while the tunnel was
        healthy. Only the ambiguous STOPPED default is worth checking against
        the OS this way — STARTING/RUNNING/ERROR were set by an action this
        process actually took and are left alone.
        """
        if self._state != ServerState.STOPPED:
            return self._state
        try:
            platform = get_server_platform()
            if platform.is_wstunnel_running() and platform.is_wg_active(
                platform.wg_interface_name()
            ):
                return ServerState.RUNNING
        except Exception:
            log.debug("effective_state: platform probe failed", exc_info=True)
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
            if self._wstunnel is None and self.effective_state == ServerState.RUNNING:
                # Already running under a process we don't own (the systemd
                # unit, or a sibling `serve` container) — adopt that state
                # instead of racing it to bind the same port.
                self._set_state(ServerState.RUNNING)
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

        if self._enroll_server is not None:
            try:
                self._enroll_server.shutdown()
                self._enroll_server.server_close()
            except Exception:
                log.exception("Error stopping enrolment listener")
            self._enroll_server = None

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

    def add_client(self, name: str, *, expires_at: str = "") -> bytes:
        """Register a new client and return its .owcfg content.

        Delegates to :func:`outwarp_server.operations.add_client` so the GUI,
        the TUI and the CLI all take exactly one path through key handling —
        this used to be a second implementation, and it is the kind of
        duplication that quietly diverges.

        Enrolment mode: the profile carries a one-time token instead of a
        private key, and the peer is admitted when the client redeems it.
        `expires_at` is an optional ISO date (YYYY-MM-DD); the client refuses an
        expired profile and `prune_expired` can revoke it server-side.

        Like `rotate_client_keys`, the file is written to a private temp dir
        that is gone before this returns: this manager lives inside a
        long-running GUI/panel whose cwd is wherever systemd or the container
        started it, and a token-bearing profile has no business sitting there
        unread. The GUI's save dialog and the panel's download get the bytes.
        """
        from outwarp_server import operations

        tmp_dir = Path(tempfile.mkdtemp(prefix="outwarp-add-"))
        try:
            with self._lock:
                result = operations.add_client(
                    self._config,
                    name,
                    config_path=self._config_path,
                    output_dir=tmp_dir,
                    expires_at=expires_at,
                    enroll=True,
                )
                self._config = result.config
                self._config_stamp = self._current_config_stamp()
            owcfg_bytes = result.owcfg_path.read_bytes()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info("Client '%s' added", name)
        return owcfg_bytes

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

    def rotate_client_keys(self, name: str) -> tuple[bytes, str]:
        """Generate a new WG keypair for an existing client and rewrite its .owcfg.

        Delegates to :func:`outwarp_server.operations.rotate_client` — the
        same path `add_client` takes — instead of duplicating key handling.
        The .owcfg is written to a private temp directory that is deleted
        before this returns: ServerManager runs as a long-lived daemon, so
        `Path.cwd()` is whatever directory systemd or the container started it
        in, not somewhere a client's rotated private key should sit
        indefinitely (it used to, unread and undeleted, until the next
        `rotate-client`). Returns (owcfg_bytes, new_public_key); since no file
        survives the call, the caller gets the content directly.
        """
        from outwarp_server import operations

        tmp_dir = Path(tempfile.mkdtemp(prefix="outwarp-rotate-"))
        try:
            with self._lock:
                result = operations.rotate_client(
                    self._config, name, config_path=self._config_path, output_dir=tmp_dir,
                )
                self._config = result.config
                self._config_stamp = self._current_config_stamp()
            owcfg_bytes = result.owcfg_path.read_bytes()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if result.wg_persist_warning:
            log.warning("Could not persist WG config: %s", result.wg_persist_warning)
        log.info("Client '%s' keys rotated", name)
        return owcfg_bytes, result.client.public_key

    def revoke_client(self, name: str) -> None:
        """Remove a client from the running interface and persist the new config.

        Delegates to :func:`outwarp_server.operations.revoke_client` — the
        same path `add_client`/`rotate_client_keys` take — instead of
        duplicating key handling. This used to reimplement the read-modify-
        write itself, which also meant it (unlike the CLI's `revoke-client`)
        forgot to invalidate any enrolment token still outstanding for the
        name, letting a revoked slot come back the moment someone redeemed it.
        """
        from outwarp_server import operations

        with self._lock:
            try:
                result = operations.revoke_client(
                    self._config, name, config_path=self._config_path,
                )
            except KeyError as exc:
                raise ValueError(f"Client '{name}' not found") from exc
            self._config = result.config
            self._config_stamp = self._current_config_stamp()

        if result.wg_persist_warning:
            log.warning("Could not persist WG config: %s", result.wg_persist_warning)
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
            # CONCEPTO-D: a client whose expires_at passed while the server was
            # off must not come back just because nobody ran `prune-expired` —
            # revoke it (peer removal + token invalidation) before the interface
            # comes up, not just exclude it from the config wireguard.py builds
            # (that filter is the belt to this suspenders, for every reconcile
            # in between restarts).
            try:
                self.prune_expired()
            except Exception:
                log.exception("prune_expired at startup failed (continuing)")

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

            # reconcile() does OS-level setup (IP forwarding, NAT, firewall)
            # before touching the WG interface — it raises PlatformError if
            # the NAT can't be created; propagate it.
            log.info("Installing WireGuard server interface")
            try:
                platform.reconcile(
                    _get_wg_conf(self._config),
                    subnet=self._config.subnet,
                    wss_port=self._config.port,
                )
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
                text=True,
                encoding="utf-8",
                errors="replace",
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

            self._start_enroll_listener()

        except Exception:
            log.exception("Unexpected error starting server")
            self._set_state(ServerState.ERROR)

    def _start_enroll_listener(self) -> None:
        """Bring up the token-redemption endpoint alongside the transport.

        Failing to bind is logged and swallowed: a tunnel that works for every
        already-enrolled client is far better than refusing to start because new
        ones cannot be admitted right now.
        """
        try:
            from outwarp_server import enroll_server
            self._enroll_server = enroll_server.serve(
                self._config, self._config_path, on_enrolled=self._on_enrolled,
            )
        except Exception:
            log.exception(
                "Could not start the enrolment listener on port %s — clients holding "
                "an enrolment profile will not be able to complete import",
                self._config.enroll_port,
            )
            self._enroll_server = None

    def _on_enrolled(self, name: str) -> None:
        """Refresh the in-memory config after a client enrolled out-of-band.

        The listener writes the new peer straight to disk, so without this the
        manager's copy would keep reporting the client as pending.
        """
        del name
        try:
            self._config = ServerConfig.load(self._config_path)
            self._config_stamp = self._current_config_stamp()
        except Exception:
            log.exception("Could not reload config after enrolment")

    def _read_output(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    log.info("[wstunnel] %s", stripped)
        except Exception:
            log.debug("_read_output: stdout reader exited unexpectedly", exc_info=True)

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(_MONITOR_INTERVAL):
            if self._state != ServerState.RUNNING:
                break
            proc = self._wstunnel
            if proc is not None and proc.poll() is not None:
                log.error("wstunnel exited unexpectedly (code=%d)", proc.returncode)
                self._set_state(ServerState.ERROR)
                break
