"""Console client for OutWarp — Linux/headless flavour.

`outwarp` (the GUI) wraps the same TunnelManager in a pywebview window. This
module exposes it as a foreground CLI instead, suitable for servers without a
display and for systemd-managed deployments.

Designed to mirror the `outwarp-server` CLI ergonomics: argparse subcommands,
a privileged helper for system mutations (already installed by
installer/linux/install.sh), no daemonisation — `outwarp-cli connect` blocks
until SIGTERM/Ctrl+C, which is the model OpenVPN/wg-quick/systemd users
expect.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from outwarp import __version__
from outwarp.config import (
    ClientConfig,
    ConfigError,
    default_config_path,
    import_owcfg,
    original_config_path,
)
from outwarp.logs import default_log_path, setup_logging
from outwarp.platforms import PlatformError, get_platform
from outwarp.tunnel import TunnelError, TunnelManager, TunnelState

log = logging.getLogger(__name__)


_STATE_LABELS: dict[TunnelState, str] = {
    TunnelState.DISCONNECTED: "disconnected",
    TunnelState.CONNECTING:   "connecting",
    TunnelState.CONNECTED:    "connected",
    TunnelState.RECONNECTING: "reconnecting",
    TunnelState.FAILED:       "failed",
}


def _print(msg: str = "") -> None:
    """Plain print wrapper — keeps every user-facing line in one place so we
    can swap the stream or add prefixes later without grepping the module."""
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _load_config() -> ClientConfig | None:
    """Return the imported profile, or None (after printing an error) if it
    can't be loaded. Callers translate that to `return 1` so main() always
    sees a real int rather than a SystemExit raised mid-handler."""
    path = default_config_path()
    try:
        return ClientConfig.load(path)
    except ConfigError as exc:
        _err(f"Error: {exc}")
        _err("Run 'outwarp-cli import <path-to-.owcfg>' first.")
        return None


# ── Subcommands ──────────────────────────────────────────────────────────────


def _cmd_import(args: argparse.Namespace) -> int:
    src = Path(args.path).expanduser()
    if not src.exists():
        _err(f"Error: file not found: {src}")
        return 1

    try:
        config = import_owcfg(src)
    except ConfigError as exc:
        _err(f"Error: invalid .owcfg — {exc}")
        return 1

    dest = default_config_path()
    _print(f"Imported profile from {src}")
    _print(f"  Saved to:  {dest}")
    _print(f"  Server:    {config.server.endpoint}:{config.server.port}")
    if config.name:
        _print(f"  Name:      {config.name}")
    _print(f"  WG iface:  {config.wireguard.tunnel_name}")
    _print(f"  WG addr:   {config.wireguard.client_address}")
    _print("")
    _print("Start the tunnel with: outwarp-cli connect")
    return 0


def _cmd_connect(args: argparse.Namespace) -> int:
    setup_logging()
    config = _load_config()
    if config is None:
        return 1

    manager = TunnelManager(
        config,
        allow_tls_intercept=args.allow_tls_intercept,
    )

    last_state: list[TunnelState] = [TunnelState.DISCONNECTED]

    def _on_state(state: TunnelState) -> None:
        # _set_state already filters same-state transitions; we still guard
        # against the listener firing for phase changes (state unchanged).
        if state == last_state[0]:
            return
        last_state[0] = state
        label = _STATE_LABELS.get(state, state.value)
        if state == TunnelState.FAILED:
            err = manager.last_error or "unknown error"
            _err(f"[state] {label}: {err}")
        else:
            _print(f"[state] {label}")

    manager.add_listener(_on_state)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    _print(f"OutWarp client v{__version__} — connecting to "
           f"{config.server.endpoint}:{config.server.port}")
    _print("Send SIGTERM or press Ctrl+C to disconnect.")
    manager.start()

    # Block until a stop signal arrives OR the manager hits FAILED. Polling
    # every 500 ms is plenty — we're not chasing latency here, just keeping
    # the foreground process alive without busy-spinning.
    while not stop.is_set():
        if manager.state == TunnelState.FAILED:
            _err("Tunnel failed; giving up.")
            manager.stop()
            return 1
        if stop.wait(0.5):
            break

    _print("Disconnecting...")
    manager.stop()
    _print("Done.")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    path = default_config_path()
    if not path.exists():
        _print("No profile imported.")
        _print(f"  Expected config at: {path}")
        _print("  Run: outwarp-cli import <path-to-.owcfg>")
        return 0

    config = _load_config()
    if config is None:
        return 1
    try:
        active = get_platform().is_wg_tunnel_active(config.wireguard.tunnel_name)
    except PlatformError as exc:
        active = None
        active_err = str(exc)
    else:
        active_err = None

    _print(f"Profile:     {config.name or '(unnamed)'}")
    _print(f"Server:      {config.server.endpoint}:{config.server.port}")
    _print(f"WG iface:    {config.wireguard.tunnel_name}")
    _print(f"WG address:  {config.wireguard.client_address}")
    if active is True:
        _print("WG status:   active")
    elif active is False:
        _print("WG status:   inactive")
    else:
        _print(f"WG status:   unknown ({active_err})")
    _print(f"Config:      {path}")
    _print(f"Log file:    {default_log_path()}")
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    config = _load_config()
    if config is None:
        return 1
    _print(f"Name:                 {config.name or '(unnamed)'}")
    _print(f"Server endpoint:      {config.server.endpoint}:{config.server.port}")
    _print(f"TLS fingerprint:      {config.tls.cert_fingerprint_sha256}")
    _print(f"WG tunnel name:       {config.wireguard.tunnel_name}")
    _print(f"WG client address:    {config.wireguard.client_address}")
    _print(f"WG MTU:               {config.wireguard.mtu}")
    _print(f"WG DNS:               {', '.join(config.wireguard.dns)}")
    _print(f"Bypass IPs:           {', '.join(config.routing.bypass_ips) or '(none)'}")
    _print(f"Local UDP port:       {config.tunnel.local_port}")
    _print(f"Remote WG endpoint:   {config.tunnel.remote_host}:{config.tunnel.remote_port}")
    _print(f"Reconnect attempts:   {config.reconnect.max_attempts}")
    _print(f"Reconnect delays (s): {', '.join(str(d) for d in config.reconnect.delays_seconds)}")
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    path = default_log_path()
    if not path.exists():
        _print(f"No log file yet at {path}")
        return 0

    if not args.follow:
        try:
            sys.stdout.write(path.read_text(encoding="utf-8", errors="replace"))
            sys.stdout.flush()
        except OSError as exc:
            _err(f"Error reading {path}: {exc}")
            return 1
        return 0

    # tail -f style: seek to end, then poll for appends. Rotation (the file
    # being replaced) is handled by re-opening when the inode changes.
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _err(f"Error opening {path}: {exc}")
        return 1

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    try:
        f.seek(0, os.SEEK_END)
        inode = path.stat().st_ino
        while not stop.is_set():
            line = f.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue
            # No new data — check for rotation and sleep briefly.
            try:
                current_inode = path.stat().st_ino
            except FileNotFoundError:
                current_inode = inode
            if current_inode != inode:
                f.close()
                f = path.open("r", encoding="utf-8", errors="replace")
                inode = current_inode
                continue
            time.sleep(0.25)
    finally:
        f.close()
    return 0


def _cmd_forget_profile(args: argparse.Namespace) -> int:
    """Remove the imported profile and its baseline snapshot.

    Does NOT touch the helper script, sudoers rule, autostart entry, or the
    pipx venv — for a full purge use ``outwarp-cli uninstall`` instead.
    """
    cfg = default_config_path()
    baseline = original_config_path(cfg)

    if not cfg.exists() and not baseline.exists():
        _print("Nothing to remove — no profile imported.")
        return 0

    if not args.yes:
        _print("This will delete:")
        if cfg.exists():
            _print(f"  - {cfg}")
        if baseline.exists():
            _print(f"  - {baseline}")
        answer = input("Type 'yes' to confirm: ").strip().lower()
        if answer != "yes":
            _print("Aborted.")
            return 1

    # Refuse to wipe the profile while a tunnel using it is still up. Otherwise
    # the WG service keeps running with config the user thinks they've deleted.
    if cfg.exists():
        try:
            config = ClientConfig.load(cfg)
            if get_platform().is_wg_tunnel_active(config.wireguard.tunnel_name):
                _err(
                    f"Refusing to remove profile while tunnel "
                    f"'{config.wireguard.tunnel_name}' is active. "
                    "Stop it first: kill the 'outwarp-cli connect' process."
                )
                return 1
        except (ConfigError, PlatformError) as exc:
            # Couldn't check — log and continue. Better to let the user delete
            # a corrupt profile than to wedge them out of cleanup.
            log.warning("Could not verify tunnel state before uninstall: %s", exc)

    for path in (cfg, baseline):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _err(f"Could not remove {path}: {exc}")
            return 1

    parent = cfg.parent
    if parent.exists():
        try:
            # Only rmdir if empty — preserves any sibling files the user added.
            if not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    _print("Profile removed.")
    return 0


# ── Argparse plumbing ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outwarp-cli",
        description="OutWarp client — WireGuard-over-WebSocket tunnel (console mode)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Import a .owcfg profile")
    p_import.add_argument("path", help="Path to the .owcfg file")

    p_connect = sub.add_parser(
        "connect",
        help="Bring up the tunnel in foreground (Ctrl+C / SIGTERM to disconnect)",
    )
    p_connect.add_argument(
        "--allow-tls-intercept",
        action="store_true",
        help="Tolerate TLS fingerprint mismatch (corporate/school inspection "
             "proxies). WireGuard stays end-to-end encrypted regardless.",
    )

    sub.add_parser("status", help="Show profile summary and WireGuard state")
    sub.add_parser("profile", help="Print full profile details")

    p_logs = sub.add_parser("logs", help="Show the OutWarp log file")
    p_logs.add_argument(
        "-f", "--follow", action="store_true",
        help="Tail the log file (like 'tail -f'); Ctrl+C to stop",
    )

    p_forget = sub.add_parser(
        "forget-profile",
        help="Remove the imported profile (was 'uninstall' in 0.4.x)",
    )
    p_forget.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    p_un = sub.add_parser(
        "uninstall",
        help="Purge OutWarp client entirely (venv, helper, sudoers, autostart)",
    )
    p_un.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    sub.add_parser(
        "tui",
        help="Launch the interactive Textual UI (Linux / headless)",
    )

    sub.add_parser(
        "gui",
        help="Launch the tray/pywebview GUI (was the 'outwarp' binary in 0.4.x)",
    )

    p_update = sub.add_parser(
        "update",
        help="Check GitHub Releases for a newer version and install it "
             "(needs root to upgrade /opt/pipx/venvs/outwarp-client)",
    )
    p_update.add_argument(
        "--check-only",
        action="store_true",
        help="Just report whether a newer version is available - don't install",
    )

    return parser


def _cmd_tui(args: argparse.Namespace) -> int:
    try:
        from outwarp.tui.app import OutWarpClientTUI
    except ImportError as exc:
        _err(
            "TUI not installed. Reinstall with: pip install 'outwarp-client[tui]'\n"
            f"  Underlying error: {exc}"
        )
        return 1
    return OutWarpClientTUI().run() or 0


def _cmd_gui(args: argparse.Namespace) -> int:
    """Delegate to outwarp.app:main — the pywebview tray entry-point.

    Was the dedicated ``outwarp`` binary in 0.4.x; collapsed into a subcommand
    in 0.5.0 so the Linux install surface is a single executable.
    """
    from outwarp.app import main as _gui_main
    return _gui_main() or 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    """Purge OutWarp client entirely — delegates to outwarp.uninstall.main.

    Replaces the standalone ``outwarp-uninstall`` binary that 0.4.x shipped.
    The previous behaviour (delete profile only) is now ``forget-profile``.
    """
    from outwarp.uninstall import main as _uninstall_main
    # Forward --yes when present; otherwise pass None so outwarp.uninstall.main
    # falls back to its own interactive confirmation flow.
    argv = ["--yes"] if args.yes else None
    return _uninstall_main(argv)


def _cmd_update(args: argparse.Namespace) -> int:
    """Check GitHub Releases for a newer outwarp-client wheel and install it.

    Without --check-only, the actual ``pip install --upgrade`` step needs to
    write into the pipx-managed venv at /opt/pipx/venvs/outwarp-client, so the
    command refuses to run unless invoked with root (typically via
    ``sudo outwarp-cli update``).
    """
    import contextlib
    import tempfile

    from outwarp.updater import (
        apply_linux_update,
        check_for_linux_update,
        download_installer,
        verify_download,
    )

    _print(f"Checking for updates (current: v{__version__})...")
    info = check_for_linux_update(__version__, "client")

    if info.get("error"):
        _err(f"Update check failed: {info['error']}")
        return 1

    if not info.get("available"):
        latest = info.get("latest") or __version__
        # If a newer tag exists but the release has no Linux wheel attached
        # (e.g. an older Windows-only release), say so explicitly rather than
        # claiming we're already on the latest version.
        from outwarp.updater import _is_newer as _newer
        if latest and _newer(latest, __version__) and not info.get("wheel_url"):
            _print(f"Latest release v{latest} has no Linux wheel attached.")
            _print(f"  See {info.get('html_url', '')}")
        else:
            _print(f"Already up to date (v{latest}).")
        return 0

    latest = info["latest"]
    _print(f"New version available: v{latest}")
    _print(f"  Release: {info.get('html_url', '')}")

    if args.check_only:
        _print("Run 'sudo outwarp-cli update' to install.")
        return 0

    wheel_url = info.get("wheel_url", "")
    wheel_name = info.get("wheel_name") or Path(wheel_url).name
    if not wheel_url:
        _err(f"No Linux wheel found in release v{latest} - see {info.get('html_url', '')}")
        return 1

    # ``geteuid`` is POSIX-only but the client is shipped only on Linux for
    # the Python wheel flow, so anchor the gate on the platform explicitly.
    # On Windows the installer ships the GUI wheel separately and there's no
    # ``outwarp-cli update`` flow yet.
    if sys.platform == "linux" and os.geteuid() != 0:
        _err("Root required to upgrade the venv. Run: sudo outwarp-cli update")
        return 1

    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as tmp:
        wheel_path = Path(tmp.name)

    try:
        _print(f"Downloading {wheel_name}...")
        last_milestone = [-1]

        def _progress(pct: int) -> None:
            milestone = pct // 20
            if milestone > last_milestone[0]:
                last_milestone[0] = milestone
                _print(f"  {pct}%")

        try:
            download_installer(wheel_url, wheel_path, _progress)
        except Exception as exc:
            _err(f"Download failed: {exc}")
            return 1

        ok, detail = verify_download(wheel_path, wheel_name, info.get("checksums_url", ""))
        if not ok:
            _err(f"Integrity check failed: {detail}")
            return 1
        _print(f"  {detail}")

        _print("Installing into venv (pip)...")
        try:
            apply_linux_update(wheel_path, extras="tui")
        except subprocess.TimeoutExpired:
            _err(
                "pip install timed out (network stall while resolving "
                "transitive deps?). Re-run when the connection is stable."
            )
            return 1
        except Exception as exc:
            _err(f"pip install failed: {exc}")
            return 1

        _print(f"\nUpdated to v{latest}.")
        _print("Restart 'outwarp-cli connect' (or the tray app) for changes to take effect.")
        return 0
    finally:
        with contextlib.suppress(OSError):
            wheel_path.unlink(missing_ok=True)


_COMMANDS = {
    "import":         _cmd_import,
    "connect":        _cmd_connect,
    "status":         _cmd_status,
    "profile":        _cmd_profile,
    "logs":           _cmd_logs,
    "forget-profile": _cmd_forget_profile,
    "uninstall":      _cmd_uninstall,
    "tui":            _cmd_tui,
    "gui":            _cmd_gui,
    "update":         _cmd_update,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args)
    except TunnelError as exc:
        _err(f"Tunnel error: {exc}")
        return 1
    except KeyboardInterrupt:
        _err("Interrupted.")
        return 130
