from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread

from platformdirs import user_data_dir

from outwarp.config import ClientConfig
from outwarp.network import (
    FingerprintMismatchError,
    HostileDetection,
    NetworkError,
    detect_hostile_network,
    tcp_probe,
    verify_tls_fingerprint,
)
from outwarp.platforms import Platform, get_platform
from outwarp.wireguard import build_wg_conf

_APP_NAME = "OutWarp"
_ENV_OVERRIDE = "OUTWARP_WSTUNNEL"

# Strip CSI/SGR escape sequences that wstunnel emits when it thinks stdout is
# a TTY (e.g. `\x1b[2mINFO\x1b[0m`). They show up as literal `[2m...[0m` in
# the UI's log panel otherwise.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# wstunnel pool-maintenance chatter from --connection-min-idle 3: every
# ~60 s the WS idle pool rotates and the client logs 3 "Opening TCP
# connection" + 3 "Doing TLS handshake" lines. Useful at DEBUG when
# diagnosing handshake errors but pure noise at INFO (≈8.6k lines/day for
# a long-lived tunnel, drowning out the events worth seeing). Match the
# substring after the ANSI strip so escape codes don't break the filter.
_WSTUNNEL_NOISE_RE = re.compile(
    r"INFO wstunnel::protocols::(?:tcp|tls)::server: "
    r"(?:Opening TCP connection|Doing TLS handshake)"
)

log = logging.getLogger(__name__)


class TunnelState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


StateListener = Callable[[TunnelState], None]


class TunnelError(RuntimeError):
    pass


def find_wstunnel() -> Path:
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        p = Path(override)
        if not p.exists():
            raise TunnelError(f"{_ENV_OVERRIDE} points to {override}, which does not exist")
        return p

    binary_name = "wstunnel.exe" if sys.platform == "win32" else "wstunnel"

    # PyInstaller frozen build: the Inno Setup installer drops wstunnel.exe
    # next to outwarp.exe (or one level up in the shared install root).
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (exe_dir / binary_name, exe_dir.parent / binary_name):
            if candidate.exists():
                return candidate

    standard = Path(user_data_dir(_APP_NAME)) / "bin" / binary_name
    if standard.exists():
        return standard

    on_path = shutil.which("wstunnel")
    if on_path:
        return Path(on_path)

    raise TunnelError(
        f"wstunnel binary not found. Looked at: ${_ENV_OVERRIDE}, {standard}, $PATH. "
        "Install it via the OutWarp installer or download from "
        "https://github.com/erebe/wstunnel/releases"
    )


def build_wstunnel_command(
    config: ClientConfig,
    wstunnel_bin: Path,
    port: int | None = None,
    *,
    hostile: bool = False,
) -> list[str]:
    t = config.tunnel
    s = config.server
    wss_port = port if port is not None else s.port
    forward = (
        f"udp://127.0.0.1:{t.local_port}:{t.remote_host}:{t.remote_port}?timeout_sec=0"
    )
    # Browsers never put ":443" in the Host header for wss://; some DPI boxes
    # use that as a signal of "this isn't a browser, it's a tunnel" and drop the
    # WS Upgrade. Omit the explicit port when it's the scheme default.
    endpoint = f"wss://{s.endpoint}" if wss_port == 443 else f"wss://{s.endpoint}:{wss_port}"
    # TLS cert verification is disabled by default in wstunnel v10+; fingerprint
    # pinning via verify_tls_fingerprint() is the actual identity check.
    cmd = [
        str(wstunnel_bin),
        "client",
        # Pre-establish idle TCP+TLS+WS connections so a new WG flow doesn't pay
        # the ~30-50 ms handshake cost on first packet.
        "--connection-min-idle",
        "3",
        # Keep the WS half-open detection tight so corporate NATs don't quietly
        # drop the connection after their idle timeout — wstunnel will see the
        # missed pong and reconnect instead of letting WG packets vanish.
        "--websocket-ping-frequency",
        "25s",
        "-L",
        forward,
        "--http-upgrade-path-prefix",
        s.http_upgrade_path_prefix,
    ]
    if hostile:
        # Hostile-network opt-in: bypass the system resolver (which may be
        # hijacked or returning poisoned AAAA records on captive/edu networks)
        # and force IPv4. Matches the flags the legacy WarpSocket script used.
        cmd.extend([
            "--dns-resolver", "dns://1.1.1.1",
            "--dns-resolver-prefer-ipv4",
        ])
    cmd.append(endpoint)
    return cmd


class Tunnel:
    def __init__(
        self,
        config: ClientConfig,
        platform: Platform | None = None,
        wstunnel_bin: Path | None = None,
        allow_tls_intercept: bool = False,
        phase_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._platform = platform or get_platform()
        self._wstunnel_bin = wstunnel_bin or find_wstunnel()
        self._proc: subprocess.Popen[str] | None = None
        self._stdout_thread: Thread | None = None
        self._wg_installed = False
        # When True, a pinned-fingerprint mismatch is logged and tolerated
        # instead of aborting the connection. Meant for networks that do active
        # TLS interception (corporate/school proxies): the WireGuard layer
        # inside the WebSocket is still end-to-end encrypted and authenticated,
        # so the outer TLS pin is belt-and-suspenders there. Mutable so a live
        # settings change takes effect on the next connect attempt.
        self.allow_tls_intercept = allow_tls_intercept
        # Notified at each milestone of connect() so the UI can light up the
        # corresponding step in the "Connecting…" view. None means no-op
        # (tests that don't care about phases pass nothing).
        self._phase_cb: Callable[[str], None] = phase_callback or (lambda _p: None)
        # Set after the network probe each connect() call: the UI reads this
        # to surface a "hostile network detected" toast or annotate Settings.
        # Format: HostileDetection (hostile bool + human reason).
        self.last_hostile_detection: HostileDetection | None = None

    def _drain_stdout(self) -> None:
        # An ``assert`` here would silently disappear under ``python -O``
        # (the pipx-managed venv inherits the system python's flags), so the
        # next line would AttributeError on a None stdout and lose the
        # entire wstunnel log. Explicit guard instead.
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                stripped = _ANSI_ESCAPE_RE.sub("", line).rstrip()
                if not stripped:
                    continue
                level = logging.DEBUG if _WSTUNNEL_NOISE_RE.search(stripped) else logging.INFO
                log.log(level, "wstunnel: %s", stripped)
        except Exception:
            log.debug("_drain_stdout: read loop exited unexpectedly", exc_info=True)

    def connect(self) -> None:
        s = self._config.server
        # Phases (resolve / tls / wg / ws) match the actual blocking work the
        # connect path does. There is no separate "route" phase: we exclude
        # bypass IPs from the WG AllowedIPs at config-build time instead of
        # adding host routes after the fact.
        self._phase_cb("resolve")
        # Try the primary WSS port first, then any fallback ports. A network
        # that blocks 443 may still let an alternate port through; the first
        # reachable one wins and is used for the rest of the connect.
        candidates = [s.port, *s.fallback_ports]
        chosen_port: int | None = next(
            (p for p in candidates if tcp_probe(s.endpoint, p)), None
        )
        if chosen_port is None:
            ports = ", ".join(str(p) for p in candidates)
            raise TunnelError(
                f"Cannot reach {s.endpoint} on any configured port ({ports}). The "
                "server may be down, the port(s) may not be open in the server "
                "firewall, or your network may block outbound connections to them."
            )
        if chosen_port != s.port:
            log.info("primary port %d unreachable — using fallback port %d", s.port, chosen_port)

        self._phase_cb("tls")
        try:
            verify_tls_fingerprint(
                s.endpoint, chosen_port, self._config.tls.cert_fingerprint_sha256
            )
        except FingerprintMismatchError as exc:
            if not self.allow_tls_intercept:
                raise TunnelError(str(exc)) from exc
            log.warning(
                "TLS fingerprint mismatch ignored ('allow TLS-intercepting networks' "
                "is on). This network is terminating the outer TLS connection (a "
                "corporate/school inspection proxy); WireGuard still encrypts and "
                "authenticates your traffic end-to-end. Details: %s",
                exc,
            )
        except NetworkError as exc:
            raise TunnelError(str(exc)) from exc

        try:
            # Resolve hostile_mode BEFORE bringing the WG interface up. Order
            # matters: install_wg_tunnel() captures 0.0.0.0/0 (minus the
            # endpoint), so any DNS query made afterwards is routed through
            # the tunnel — but wstunnel isn't running yet, so the query stalls
            # for the full glibc DNS retry budget (~25 s). Running the probe
            # here keeps it on the host's real resolver, where it costs
            # <300 ms instead.
            mode = self._config.network.hostile_mode
            if mode == "on":
                hostile = True
            elif mode == "off":
                hostile = False
            else:  # "auto" — probe the network once per connect attempt
                detection = detect_hostile_network(s.endpoint)
                self.last_hostile_detection = detection
                hostile = detection.hostile
                if detection.hostile:
                    log.warning(
                        "Hostile-network heuristic triggered: %s — enabling "
                        "wstunnel DNS bypass (1.1.1.1 + IPv4-only) for this session",
                        detection.reason,
                    )

            self._phase_cb("wg")
            wg_conf = build_wg_conf(self._config)
            self._platform.install_wg_tunnel(self._config.wireguard.tunnel_name, wg_conf)
            self._wg_installed = True

            self._phase_cb("ws")
            cmd = build_wstunnel_command(
                self._config, self._wstunnel_bin, port=chosen_port, hostile=hostile,
            )
            log.info("Starting wstunnel: %s", " ".join(cmd))
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # wstunnel emits UTF-8 on stdout. The default `text=True`
                # uses the system locale encoding (CP1252 on Spanish-Windows,
                # etc.), which mangles non-ASCII Rust error messages.
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._stdout_thread = Thread(
                target=self._drain_stdout, daemon=True, name="wstunnel-stdout"
            )
            self._stdout_thread.start()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
            except Exception as exc:
                log.warning("Error terminating wstunnel: %s", exc)
            finally:
                if self._stdout_thread is not None:
                    self._stdout_thread.join(timeout=2)
                    self._stdout_thread = None
            self._proc = None

        if self._wg_installed:
            try:
                self._platform.uninstall_wg_tunnel(self._config.wireguard.tunnel_name)
            except Exception as exc:
                log.warning("Error uninstalling WG tunnel: %s", exc)
            self._wg_installed = False


    @property
    def is_active(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        return self._platform.is_wg_tunnel_active(self._config.wireguard.tunnel_name)


def _pick_delay(delays: list[int], attempt_just_failed: int) -> int:
    if not delays:
        return 5
    idx = min(max(attempt_just_failed - 1, 0), len(delays) - 1)
    return delays[idx]


class TunnelManager:
    def __init__(
        self,
        config: ClientConfig,
        tunnel: Tunnel | None = None,
        *,
        stability_seconds: float = 30.0,
        poll_interval: float = 1.0,
        allow_tls_intercept: bool = False,
        auto_reconnect: bool = True,
    ) -> None:
        self._config = config
        # Granular progress flag set by the Tunnel mid-connect ("resolve",
        # "tls", "wg", "ws", "done"). Empty string between attempts. Listeners
        # fire on every phase change as well as state changes so the UI can
        # animate the connecting stepper.
        self._phase: str = ""
        self._tunnel = tunnel or Tunnel(
            config,
            allow_tls_intercept=allow_tls_intercept,
            phase_callback=self._set_phase,
        )
        self._stability = stability_seconds
        self._poll = poll_interval
        self._state = TunnelState.DISCONNECTED
        self._last_error: str | None = None
        self._attempt = 0
        self._lock = Lock()
        self._listeners: list[StateListener] = []
        self._stop_event = Event()
        self._thread: Thread | None = None
        # When False, an unexpectedly-closed tunnel goes straight to FAILED
        # instead of looping through max_attempts retries. Initial-connect
        # failures still honour max_attempts — the user explicitly asked to
        # connect, so giving up immediately would surprise them.
        self._auto_reconnect = bool(auto_reconnect)

    @property
    def state(self) -> TunnelState:
        with self._lock:
            return self._state

    @property
    def last_error(self) -> str | None:
        """Human-readable reason for the most recent failure, or None.

        Cleared on a successful connection and on stop()."""
        with self._lock:
            return self._last_error

    @property
    def attempt(self) -> int:
        """How many connect attempts have failed in the current streak.

        0 while connecting fresh or once a connection has held; >0 while
        reconnecting after a drop. Resets after the stability window."""
        with self._lock:
            return self._attempt

    @property
    def config(self) -> ClientConfig:
        return self._config

    @property
    def allow_tls_intercept(self) -> bool:
        return self._tunnel.allow_tls_intercept

    @allow_tls_intercept.setter
    def allow_tls_intercept(self, value: bool) -> None:
        # Picked up on the next connect attempt — no need to restart the tunnel.
        self._tunnel.allow_tls_intercept = bool(value)

    @property
    def last_hostile_detection(self) -> HostileDetection | None:
        """Most recent hostile-network probe result, or None if mode != auto.

        Set by Tunnel.connect() each attempt. The UI reads this on state
        transitions to surface a "DNS interception detected" toast/banner so
        the user knows wstunnel is silently using the public resolver."""
        return self._tunnel.last_hostile_detection

    @property
    def auto_reconnect(self) -> bool:
        return self._auto_reconnect

    @auto_reconnect.setter
    def auto_reconnect(self, value: bool) -> None:
        # Live setting; affects the next unexpected-death path. We deliberately
        # do not touch a retry that's already in flight.
        self._auto_reconnect = bool(value)

    @property
    def phase(self) -> str:
        with self._lock:
            return self._phase

    def _set_phase(self, phase: str) -> None:
        """Update the connect-phase flag and notify listeners.

        Listeners receive the current state (unchanged) so they can re-emit a
        status payload that includes the new phase. Status listeners must be
        idempotent on same-state — they already are: api._on_state_change
        re-emits status and the kill-switch sync is a no-op when nothing has
        actually changed."""
        with self._lock:
            if self._phase == phase:
                return
            self._phase = phase
            state = self._state
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(state)
            except Exception:
                log.exception("Phase listener raised")

    def _set_error(self, msg: str | None) -> None:
        with self._lock:
            self._last_error = msg

    def _set_attempt(self, n: int) -> None:
        with self._lock:
            self._attempt = n

    def add_listener(self, callback: StateListener) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: StateListener) -> None:
        """Detach a listener. Used when swapping managers so a stopping manager
        can't keep emitting state changes that race the replacement."""
        with self._lock, contextlib.suppress(ValueError):
            self._listeners.remove(callback)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, daemon=True, name="outwarp-tunnel")
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        try:
            self._tunnel.disconnect()
        except Exception:
            log.exception("Error while disconnecting tunnel during stop()")
        self._set_error(None)
        self._set_attempt(0)
        self._set_phase("")
        self._set_state(TunnelState.DISCONNECTED)

    def _set_state(self, state: TunnelState) -> None:
        with self._lock:
            if self._state == state:
                return
            self._state = state
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(state)
            except Exception:
                log.exception("State listener raised")

    def _run(self) -> None:
        attempt = 0
        max_attempts = self._config.reconnect.max_attempts
        delays = self._config.reconnect.delays_seconds
        self._set_attempt(0)

        while not self._stop_event.is_set():
            # Each attempt restarts the stepper from the beginning.
            self._set_phase("")
            self._set_state(
                TunnelState.CONNECTING if attempt == 0 else TunnelState.RECONNECTING
            )
            try:
                self._tunnel.connect()
            except Exception as exc:
                log.warning("Connect attempt %d failed: %s", attempt + 1, exc)
                self._set_error(str(exc))
                attempt += 1
                self._set_attempt(attempt)
                if attempt >= max_attempts:
                    self._set_state(TunnelState.FAILED)
                    return
                if self._stop_event.wait(_pick_delay(delays, attempt)):
                    return
                continue

            self._set_error(None)
            # Mark the stepper complete just before flipping to CONNECTED so
            # the UI's last "active" step settles into "done" alongside the
            # state transition rather than after it.
            self._set_phase("done")
            self._set_state(TunnelState.CONNECTED)
            connected_at = time.monotonic()
            stability_reset = False

            while not self._stop_event.is_set():
                if not self._tunnel.is_active:
                    break
                if not stability_reset and time.monotonic() - connected_at >= self._stability:
                    attempt = 0
                    self._set_attempt(0)
                    stability_reset = True
                if self._stop_event.wait(self._poll):
                    return

            if self._stop_event.is_set():
                return

            log.warning("Tunnel died unexpectedly; cleaning up before retry")
            self._set_error("La conexión se cerró inesperadamente")
            try:
                self._tunnel.disconnect()
            except Exception:
                log.exception("Cleanup after unexpected tunnel death failed")

            if not self._auto_reconnect:
                # User opted out of post-connection retries. Surface the failure
                # so the UI can prompt to reconnect manually.
                log.info("auto_reconnect=off — not retrying after tunnel death")
                self._set_state(TunnelState.FAILED)
                return

            attempt += 1
            self._set_attempt(attempt)
            if attempt >= max_attempts:
                self._set_state(TunnelState.FAILED)
                return
            if self._stop_event.wait(_pick_delay(delays, attempt)):
                return
