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
from outwarp.fallback import (
    ConnectionStrategy,
    StickyStore,
    all_bypass_ips,
    build_ladder,
    default_sticky_path,
    network_signature,
    reorder_for_sticky,
    strategy_to_command,
)
from outwarp.network import (
    CertificateNotTrustedError,
    FingerprintMismatchError,
    HostileDetection,
    NetworkError,
    detect_hostile_network,
    measure_latency_ms,
    tcp_probe,
    verify_tls_ca,
    verify_tls_fingerprint,
    verify_tls_spki,
)
from outwarp.platforms import Platform, get_platform
from outwarp.wireguard import build_wg_conf, get_tunnel_stats

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


def _forward_spec(config: ClientConfig) -> str:
    t = config.tunnel
    return f"udp://127.0.0.1:{t.local_port}:{t.remote_host}:{t.remote_port}?timeout_sec=0"


def build_wstunnel_command(
    config: ClientConfig,
    wstunnel_bin: Path,
    port: int | None = None,
    *,
    hostile: bool = False,
) -> list[str]:
    """Build the wstunnel argv for the plain direct rung.

    Thin wrapper kept for callers/tests that want the canonical direct command;
    the fallback ladder builds richer strategies via
    outwarp.fallback.strategy_to_command. The default WSS port is omitted from
    the URL (see ConnectionStrategy.url) because some DPI boxes treat an explicit
    ":443" as a "this is a tunnel, not a browser" signal.
    """
    s = config.server
    strategy = ConnectionStrategy(
        id="direct",
        label="Direct",
        endpoint=s.endpoint,
        port=port if port is not None else s.port,
        path_prefix=s.http_upgrade_path_prefix,
        force_hostile=hostile,
    )
    return strategy_to_command(strategy, wstunnel_bin, _forward_spec(config))


class Tunnel:
    def __init__(
        self,
        config: ClientConfig,
        platform: Platform | None = None,
        wstunnel_bin: Path | None = None,
        allow_tls_intercept: bool = False,
        phase_callback: Callable[[str], None] | None = None,
        handshake_timeout: float = 12.0,
        verify_ping_target: str = "1.1.1.1",
        require_ping: bool = True,
    ) -> None:
        self._config = config
        self._platform = platform or get_platform()
        self._wstunnel_bin = wstunnel_bin or find_wstunnel()
        self._proc: subprocess.Popen[str] | None = None
        self._stdout_thread: Thread | None = None
        self._wg_installed = False
        # Fallback-ladder tuning. A rung is accepted only when a fresh WG
        # handshake appears within handshake_timeout AND (when require_ping) a
        # ping reaches verify_ping_target *through* the tunnel — a live wstunnel
        # process alone is not proof the WS upgrade actually passed.
        self._handshake_timeout = handshake_timeout
        self._verify_ping_target = verify_ping_target
        self._require_ping = require_ping
        # Set by TunnelManager from the sticky store: the rung that last worked
        # on this network, tried first. Empty = start from the top of the ladder.
        self.preferred_strategy_id = ""
        # The rung that actually connected, or None. Read by the manager to
        # persist stickiness and by the UI to show which front is in use.
        self._active_strategy: ConnectionStrategy | None = None
        # Optional per-rung progress hook: (label, index, total). Lets the UI
        # show "Trying via proxy… (3/5)". No-op by default.
        self.strategy_callback: Callable[[str, int, int], None] = lambda _l, _i, _t: None
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

    @property
    def platform(self) -> Platform:
        return self._platform

    @property
    def active_strategy(self) -> ConnectionStrategy | None:
        """The rung that carried the current connection, or None."""
        return self._active_strategy

    @property
    def active_strategy_id(self) -> str:
        return self._active_strategy.id if self._active_strategy else ""

    def connect(self) -> None:
        """Bring the tunnel up by walking the fallback ladder.

        WireGuard is installed once (excluding every rung's endpoint from the
        tunnel), then each strategy is tried until one produces a WG handshake
        and a ping through the tunnel. Phases (resolve / tls / wg / ws) drive the
        UI stepper; there is no separate "route" phase because bypass IPs are
        excluded from AllowedIPs at config-build time, not added as host routes.
        """
        s = self._config.server
        if not self._config.wireguard.client_private_key:
            # Only reachable if enrolment was interrupted or the saved profile
            # was hand-edited; without a key wg-quick would fail with something
            # far less informative.
            raise TunnelError(
                "This profile has no WireGuard key yet — enrolment did not "
                "complete. Import the .owcfg again to retry; if its token has "
                "expired, ask the server admin for a new profile."
            )
        self._active_strategy = None
        self._phase_cb("resolve")

        ladder = build_ladder(self._config)
        if not self._config.fallback.enabled:
            # Ladder disabled: keep only the single best rung so behaviour is a
            # plain one-shot connect (still with handshake+ping verification).
            ladder = ladder[:1]
        ladder = reorder_for_sticky(ladder, self.preferred_strategy_id)
        if not ladder:
            raise TunnelError("No connection strategy available for this profile.")

        # Informational only: the hostile heuristic still feeds the UI banner,
        # but the ladder — not this probe — decides which transport actually runs.
        if self._config.network.hostile_mode == "auto":
            with contextlib.suppress(Exception):
                self.last_hostile_detection = detect_hostile_network(s.endpoint)

        # Pre-flight reachability: a direct WSS rung is only attemptable if its
        # port answers a TCP connect. Proxy / plain-ws / CDN rungs can't be
        # cheaply probed (the direct path may be exactly what's blocked), so they
        # are always attemptable. If nothing is dialable, fail fast BEFORE
        # touching WireGuard so the interface isn't churned pointlessly.
        attemptable = [r for r in ladder if self._is_attemptable(r)]
        if not attemptable:
            ports = ", ".join(str(p) for p in dict.fromkeys(r.port for r in ladder))
            raise TunnelError(
                f"Cannot reach {s.endpoint} on any configured port ({ports}). The "
                "server may be down, the port(s) may not be open in the server "
                "firewall, or your network may block outbound connections to them."
            )

        try:
            self._phase_cb("tls")
            self._phase_cb("wg")
            extra_bypass = all_bypass_ips(self._config, ladder)
            wg_conf = build_wg_conf(self._config, extra_bypass=extra_bypass)
            self._platform.install_wg_tunnel(self._config.wireguard.tunnel_name, wg_conf)
            self._wg_installed = True

            total = len(attemptable)
            failures: list[str] = []
            for idx, strat in enumerate(attemptable):
                self.strategy_callback(strat.label, idx, total)
                log.info(
                    "Fallback ladder: trying rung %d/%d — %s (%s)",
                    idx + 1, total, strat.label, strat.url,
                )
                ok, reason = self._try_strategy(strat)
                if ok:
                    self._active_strategy = strat
                    self._phase_cb("ws")
                    log.info("Connected via rung '%s' (%s)", strat.id, strat.url)
                    return
                failures.append(f"{strat.label}: {reason}")
                self._stop_wstunnel()

            raise TunnelError(
                "All connection strategies failed:\n  " + "\n  ".join(failures)
            )
        except Exception:
            self.disconnect()
            raise

    def _is_attemptable(self, strat: ConnectionStrategy) -> bool:
        if strat.proxy or strat.scheme != "wss":
            return True
        return tcp_probe(strat.endpoint, strat.port, timeout=4.0)

    def _try_strategy(self, strat: ConnectionStrategy) -> tuple[bool, str]:
        """Attempt one rung. Returns (success, human_reason_if_failed).

        Leaves the wstunnel process running on success; the caller stops it
        before moving to the next rung on failure. Reachability was already
        vetted by the pre-flight in connect(); here we do the per-rung pin check
        (direct WSS only) then start wstunnel and verify handshake + traffic.
        """
        direct_wss = strat.scheme == "wss" and not strat.proxy
        if direct_wss and strat.pin_mode != "none":
            ok, reason = self._check_pin(strat)
            if not ok:
                return False, reason

        baseline = self._current_handshake()
        try:
            self._start_wstunnel(strat)
        except Exception as exc:  # noqa: BLE001 — surface as a rung failure, keep laddering
            return False, f"wstunnel failed to start: {exc}"

        if not self._await_handshake(baseline):
            return False, "no WireGuard handshake"
        if self._require_ping and not self._await_ping():
            return False, "handshake but no traffic through tunnel"
        return True, ""

    def _check_pin(self, strat: ConnectionStrategy) -> tuple[bool, str]:
        tls = self._config.tls
        if strat.pin_mode == "ca":
            # Deliberately not tolerated by allow_tls_intercept: wstunnel gets
            # --tls-verify-certificate on this rung and would refuse the
            # connection anyway, so waving it through here would only swap a
            # precise error for a mute timeout.
            try:
                verify_tls_ca(strat.endpoint, strat.port)
                return True, ""
            except CertificateNotTrustedError as exc:
                log.warning("CA verification failed on rung '%s': %s", strat.id, exc)
                return False, "TLS certificate not trusted"
            except NetworkError as exc:
                return False, f"TLS probe failed: {exc}"

        try:
            if tls.spki_sha256:
                verify_tls_spki(strat.endpoint, strat.port, tls.spki_sha256)
            else:
                verify_tls_fingerprint(
                    strat.endpoint, strat.port, tls.cert_fingerprint_sha256
                )
            return True, ""
        except FingerprintMismatchError as exc:
            if strat.pin_mode == "tolerate" or self.allow_tls_intercept:
                log.warning(
                    "TLS fingerprint mismatch tolerated on rung '%s' (TLS-intercepting "
                    "network); WireGuard still authenticates end-to-end. Details: %s",
                    strat.id, exc,
                )
                return True, ""
            return False, "TLS fingerprint mismatch"
        except NetworkError as exc:
            return False, f"TLS probe failed: {exc}"

    def _current_handshake(self) -> int | None:
        stats = get_tunnel_stats(self._config.wireguard.tunnel_name)
        return stats.latest_handshake if stats else None

    def _await_handshake(self, baseline: int | None) -> bool:
        """Poll until a handshake strictly newer than `baseline` appears."""
        deadline = time.monotonic() + self._handshake_timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False  # wstunnel died — this rung is dead
            hs = self._current_handshake()
            if hs is not None and (baseline is None or hs > baseline):
                return True
            time.sleep(0.5)
        return False

    def _await_ping(self, attempts: int = 4) -> bool:
        """Confirm packets actually traverse the tunnel to a public anycast IP."""
        for _ in range(attempts):
            if measure_latency_ms(self._verify_ping_target, timeout_ms=1500) is not None:
                return True
        return False

    def _start_wstunnel(self, strat: ConnectionStrategy) -> None:
        cmd = strategy_to_command(strat, self._wstunnel_bin, _forward_spec(self._config))
        log.info("Starting wstunnel: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # wstunnel emits UTF-8 on stdout. The default text=True uses the
            # system locale encoding (CP1252 on Spanish-Windows, etc.), which
            # mangles non-ASCII Rust error messages.
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._stdout_thread = Thread(
            target=self._drain_stdout, daemon=True, name="wstunnel-stdout"
        )
        self._stdout_thread.start()

    def _stop_wstunnel(self) -> None:
        """Terminate the wstunnel process but leave the WG interface installed.

        Used between ladder rungs: WG is invariant across strategies, so only
        the transport process is cycled.
        """
        if self._proc is None:
            return
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

    def disconnect(self) -> None:
        self._active_strategy = None
        self._stop_wstunnel()

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
        sticky_store: StickyStore | None = None,
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
        # Remembers which ladder rung last worked per network, so a repeat visit
        # starts from the winner instead of re-walking the whole ladder.
        self._sticky = sticky_store if sticky_store is not None else StickyStore(
            default_sticky_path()
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

    def _network_signature(self) -> str:
        gateway = ""
        try:
            gateway = self._tunnel.platform.get_default_gateway()
        except Exception:
            gateway = ""
        return network_signature(gateway)

    def _run(self) -> None:
        attempt = 0
        max_attempts = self._config.reconnect.max_attempts
        delays = self._config.reconnect.delays_seconds
        self._set_attempt(0)

        # Seed the ladder with whatever rung last worked on this network so a
        # repeat visit connects on the first attempt instead of re-walking it.
        signature = self._network_signature()
        self._tunnel.preferred_strategy_id = self._sticky.get(signature)

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

            # Persist the winning rung and prefer it for any reconnect in this
            # session — a transient drop should retry what worked, not re-ladder.
            won = self._tunnel.active_strategy_id
            if won:
                self._sticky.set(signature, won)
                self._tunnel.preferred_strategy_id = won

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
            self._set_error("Connection closed unexpectedly")
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
