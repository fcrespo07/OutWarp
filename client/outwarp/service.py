"""Background-service helpers for the OutWarp client.

Two concerns live here:

1. ``run_daemon()`` — long-running, silent-on-stdout TunnelManager that the
   systemd/SCM unit invokes. Mirrors ``cli._cmd_connect`` but skips the
   conversational stdout prints (state transitions go to the log file only)
   so the service journal doesn't double-log every reconnect.

2. ``install_service`` / ``uninstall_service`` / ``service_status`` — write
   and manage a per-user systemd unit on Linux. Per-user (not system) so the
   service can be set up without sudo and uses the same XDG paths the GUI/TUI
   already read; the user must run ``loginctl enable-linger`` once if they
   want it to start before they log in.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging
from outwarp.notify import notify as _notify
from outwarp.tunnel import TunnelManager, TunnelState

log = logging.getLogger(__name__)


SERVICE_NAME = "outwarp-client.service"


# ── daemon runtime ──────────────────────────────────────────────────────


def run_daemon(*, allow_tls_intercept: bool = False) -> int:
    """Run the tunnel until SIGTERM/SIGINT. Returns a shell exit code.

    Designed to be the ExecStart= target of a systemd/SCM unit: silent on
    stdout, all messages routed through the project logger (which writes to
    the rotating log file). Auto-reconnect always honours the config's
    reconnect schedule — that's exactly the loop that a background service
    needs from the user's perspective.
    """
    setup_logging()
    try:
        config = ClientConfig.load(default_config_path())
    except ConfigError as exc:
        log.error("daemon: cannot start, no profile imported (%s)", exc)
        return 2

    manager = TunnelManager(
        config,
        allow_tls_intercept=allow_tls_intercept,
        auto_reconnect=True,
    )

    last_state: list[TunnelState] = [TunnelState.DISCONNECTED]

    def _on_state(state: TunnelState) -> None:
        if state == last_state[0]:
            return
        prev = last_state[0]
        last_state[0] = state
        log.info("daemon: tunnel state -> %s", state.value)
        if state is TunnelState.CONNECTED:
            _notify("OutWarp", "Connected")
        elif state is TunnelState.FAILED:
            err = manager.last_error or "unknown error"
            _notify("OutWarp", f"Connection failed: {err}", urgency="critical")
        elif state is TunnelState.RECONNECTING and prev is TunnelState.CONNECTED:
            _notify("OutWarp", "Connection dropped — reconnecting...")

    manager.add_listener(_on_state)

    stop = threading.Event()
    # On Windows SCM signals raise outside the main thread; the SCM wrapper
    # will install its own control handler when we ship a Windows service.
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, lambda *_: stop.set())

    log.info("daemon: starting (endpoint=%s:%s)", config.server.endpoint, config.server.port)
    manager.start()
    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        log.info("daemon: stopping")
        manager.stop()
        log.info("daemon: stopped")
    return 0


# ── systemd --user service management (Linux) ───────────────────────────


def _user_unit_dir() -> Path:
    """Resolve ~/.config/systemd/user using XDG semantics — same path the
    user's systemctl --user reads, so an externally-edited unit and our
    writes don't fight over locations."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _resolve_daemon_executable() -> Path:
    """Return the absolute path that the unit's ExecStart= should point at.

    Picks ``outwarp-cli`` from PATH first so a system-wide pipx install at
    /usr/local/bin wins over the in-repo dev script. Falls back to argv[0]
    when nothing is on PATH (test/dev scenarios)."""
    exe = shutil.which("outwarp-cli")
    if exe:
        return Path(exe).resolve()
    return Path(sys.argv[0]).resolve()


def _unit_content(exe_path: Path) -> str:
    # systemd is Linux-only; the unit must use POSIX separators even when the
    # generator runs on Windows (the unit-content tests run on every OS in CI).
    # str(PurePosixPath) would also work but as_posix() is the documented hook.
    exe_str = exe_path.as_posix()
    return (
        "[Unit]\n"
        "Description=OutWarp client (WireGuard over WebSocket)\n"
        "Documentation=https://github.com/fcrespo07/OutWarp\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exe_str} daemon\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        # Tunnel state lives in $HOME/.config and $HOME/.local/state, so
        # no extra ReadWritePaths needed. The privileged helper is invoked
        # via sudo NOPASSWD from the running user's session.
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True, check=False,
    )


# ── linger helpers ───────────────────────────────────────────────────────


def is_linger_enabled() -> bool:
    """Return True if systemd user linger is enabled for the current user.

    Checks the filesystem directly (no subprocess) — fast and root-free.
    Always False on non-Linux or when the user can't be determined.
    """
    if sys.platform != "linux":
        return False
    user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
    return bool(user) and Path(f"/var/lib/systemd/linger/{user}").exists()


def set_linger(enable: bool) -> tuple[bool, str]:
    """Try to enable or disable systemd user linger without a password prompt.

    Tries ``loginctl`` directly first (works on systemd >= 240 for own
    user); falls back to ``sudo -n loginctl`` (works when the user has a
    relevant NOPASSWD sudoers rule). Returns ``(True, "")`` on success or
    ``(False, hint_message)`` on failure.
    """
    if sys.platform != "linux":
        return False, "Linger management is only supported on Linux"
    user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
    if not user:
        return False, "Cannot determine current user"
    if shutil.which("loginctl") is None:
        return False, "loginctl not found — install systemd"

    action = "enable-linger" if enable else "disable-linger"
    for cmd in (
        ["loginctl", action, user],
        ["sudo", "-n", "loginctl", action, user],
    ):
        if cmd[0] == "sudo" and shutil.which("sudo") is None:
            continue
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode == 0:
            return True, ""

    return False, f"Run as root: sudo loginctl {action} {user}"


def install_service() -> int:
    """Write the unit, reload the user manager, enable + start the service.

    Returns 0 on success, non-zero on the first failing step. Stays
    idempotent: re-running overwrites the unit and re-enables, which is
    what users expect after editing their profile manually.
    """
    if sys.platform != "linux":
        print("Service install is only supported on Linux for now.", file=sys.stderr)
        print("On Windows, register OutWarp as a Service via the installer.", file=sys.stderr)
        return 2
    if shutil.which("systemctl") is None:
        print("systemctl not found — only systemd-based distros are supported.", file=sys.stderr)
        return 2

    unit_dir = _user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / SERVICE_NAME

    exe_path = _resolve_daemon_executable()
    unit_path.write_text(_unit_content(exe_path), encoding="utf-8")
    print(f"Wrote {unit_path}")
    print(f"  ExecStart={exe_path.as_posix()} daemon")

    for step in (("daemon-reload",), ("enable", "--now", SERVICE_NAME)):
        res = _systemctl(*step)
        if res.returncode != 0:
            print(f"systemctl --user {' '.join(step)} failed:", file=sys.stderr)
            print(res.stderr.strip() or res.stdout.strip(), file=sys.stderr)
            return res.returncode or 1

    print("\nService enabled. Check status with:")
    print(f"  systemctl --user status {SERVICE_NAME}")

    ok, hint = set_linger(True)
    if ok:
        print("\nLinger enabled — service will start at boot before login.")
    else:
        print("\nTo start before login, run once as root:")
        print(f"  sudo loginctl enable-linger {os.environ.get('USER', '<your-user>')}")
    return 0


def uninstall_service() -> int:
    """Stop + disable + remove the unit. Best-effort: continues past
    failures so a half-installed state can still be cleaned."""
    if sys.platform != "linux":
        print("Service uninstall is only supported on Linux.", file=sys.stderr)
        return 2
    if shutil.which("systemctl") is None:
        print("systemctl not found — nothing to uninstall.", file=sys.stderr)
        return 0

    # Tolerate "unit not found" exits — we still want to delete the file.
    _systemctl("disable", "--now", SERVICE_NAME)

    unit_path = _user_unit_dir() / SERVICE_NAME
    if unit_path.exists():
        unit_path.unlink()
        print(f"Removed {unit_path}")
    else:
        print(f"No unit file at {unit_path}")

    _systemctl("daemon-reload")
    _systemctl("reset-failed", SERVICE_NAME)
    print("Service uninstalled.")
    return 0


def service_status() -> int:
    """Pass through ``systemctl --user status``. Returns systemctl's own
    exit code so the caller's shell sees the canonical 0/3/4 codes."""
    if sys.platform != "linux":
        print("Service status is only supported on Linux.", file=sys.stderr)
        return 2
    if shutil.which("systemctl") is None:
        print("systemctl not found.", file=sys.stderr)
        return 2

    # Use call (not run) so the output streams to the terminal in real
    # time — matches the UX of a direct ``systemctl --user status`` call.
    return subprocess.call(
        ["systemctl", "--user", "status", SERVICE_NAME, "--no-pager"],
    )
