"""Console client for OutWarp — Linux/headless flavour.

`outwarp` (the GUI) wraps the same TunnelManager in a pywebview window. This
module exposes it as a foreground CLI instead, suitable for servers without a
display and for systemd-managed deployments.

Designed to mirror the `outwarp-server` CLI ergonomics: argparse subcommands,
a privileged helper for system mutations (already installed by
installer/linux/install.sh), no daemonisation — `outwarp connect` blocks
until SIGTERM/Ctrl+C, which is the model OpenVPN/wg-quick/systemd users
expect.
"""
from __future__ import annotations

import argparse
import logging
import os
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
    import_owcfg_with_verdict,
    original_config_path,
)
from outwarp.i18n import t
from outwarp.logs import default_log_path, setup_logging
from outwarp.platforms import PlatformError, get_platform
from outwarp.tunnel import TunnelError, TunnelManager, TunnelState

log = logging.getLogger(__name__)


def _state_label(state: TunnelState) -> str:
    return t(f"cli.state.{state.value}")


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
        _err(t("cli.error", error=exc))
        _err(t("cli.run_import_first"))
        return None


# ── Subcommands ──────────────────────────────────────────────────────────────


def _cmd_import(args: argparse.Namespace) -> int:
    src = Path(args.path).expanduser()
    if not src.exists():
        _err(t("cli.file_not_found", path=src))
        return 1

    try:
        config, trust_verdict = import_owcfg_with_verdict(src)
    except ConfigError as exc:
        _err(t("cli.invalid_owcfg", error=exc))
        return 1

    from outwarp import profiles

    profile_id = profiles.active_id() or ""
    _print(t("cli.imported", path=src))
    _print(t("cli.import.profile", id=profile_id))
    _print(t("cli.import.saved", path=profiles.config_path(profile_id)))
    _print(t("cli.import.server", server=f"{config.server.endpoint}:{config.server.port}"))
    if config.name:
        _print(t("cli.import.name", name=config.name))
    _print(t("cli.import.iface", iface=config.wireguard.tunnel_name))
    _print(t("cli.import.addr", addr=config.wireguard.client_address))
    _print(t("cli.import.signature", verdict=trust_verdict.message))
    _print("")
    _print(t("cli.import.next"))
    return 0


def _cmd_connect(args: argparse.Namespace) -> int:
    setup_logging()
    config = _load_config()
    if config is None:
        return 1

    from outwarp.killswitch import release_stale_async
    from outwarp.ownership import OWNED_ELSEWHERE_HINT, TunnelOwnerLock, describe_owner
    from outwarp.settings import load_settings

    lock = TunnelOwnerLock()
    if not lock.acquire():
        _err(t("cli.owned_elsewhere", owner=describe_owner(), hint=OWNED_ELSEWHERE_HINT))
        return 1

    # The toggles both UIs persist apply here too — a user who enabled the
    # kill switch or TLS-intercept tolerance in the GUI/TUI and then runs
    # `outwarp connect` from a terminal gets the same behaviour.
    settings = load_settings()
    kill_switch = bool(settings.get("kill_switch", False))
    if not kill_switch:
        release_stale_async()
    manager = TunnelManager(
        config,
        allow_tls_intercept=args.allow_tls_intercept
        or bool(settings.get("allow_tls_intercept", False)),
        auto_reconnect=bool(settings.get("auto_reconnect", True)),
        kill_switch_enabled=kill_switch,
    )

    last_state: list[TunnelState] = [TunnelState.DISCONNECTED]

    def _on_state(state: TunnelState) -> None:
        # _set_state already filters same-state transitions; we still guard
        # against the listener firing for phase changes (state unchanged).
        if state == last_state[0]:
            return
        last_state[0] = state
        label = _state_label(state)
        if state == TunnelState.FAILED:
            err = manager.last_error or t("cli.unknown_error")
            _err(t("cli.state.line_error", label=label, error=err))
        else:
            _print(t("cli.state.line", label=label))

    manager.add_listener(_on_state)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    _print(t("cli.connecting", version=__version__,
             server=f"{config.server.endpoint}:{config.server.port}"))
    _print(t("cli.connect.stop_hint"))
    manager.start()

    # Block until a stop signal arrives OR the manager hits FAILED. Polling
    # every 500 ms is plenty — we're not chasing latency here, just keeping
    # the foreground process alive without busy-spinning.
    try:
        while not stop.is_set():
            if manager.state == TunnelState.FAILED:
                _err(t("cli.connect.gave_up"))
                manager.stop()
                return 1
            if stop.wait(0.5):
                break

        _print(t("cli.connect.disconnecting"))
        manager.stop()
        _print(t("cli.done"))
        return 0
    finally:
        lock.release()


def _cmd_status(args: argparse.Namespace) -> int:
    path = default_config_path()
    if not path.exists():
        _print(t("cli.status.none"))
        _print(t("cli.status.expected", path=path))
        _print(t("cli.status.run_import"))
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

    _print(t("cli.status.profile", name=config.name or t("cli.unnamed")))
    _print(t("cli.status.server", server=f"{config.server.endpoint}:{config.server.port}"))
    _print(t("cli.status.iface", iface=config.wireguard.tunnel_name))
    _print(t("cli.status.addr", addr=config.wireguard.client_address))
    if active is True:
        _print(t("cli.status.wg_active"))
    elif active is False:
        _print(t("cli.status.wg_inactive"))
    else:
        _print(t("cli.status.wg_unknown", error=active_err))
    _print(t("cli.status.config", path=path))
    _print(t("cli.status.logfile", path=default_log_path()))
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    action = getattr(args, "profile_action", None)
    if action == "list":
        return _profile_list()
    if action == "use":
        return _profile_use(args.id)
    if action == "remove":
        return _profile_remove(args.id, assume_yes=args.yes)
    return _profile_show()


def _profile_list() -> int:
    from outwarp import profiles

    refs = profiles.list_profiles()
    if not refs:
        _print(t("cli.profile.none"))
        return 0
    active = profiles.active_id()
    for ref in refs:
        try:
            cfg = ClientConfig.load(ref.path)
            detail = f"{cfg.name or t('cli.unnamed')}  {cfg.server.endpoint}:{cfg.server.port}"
            if cfg.is_expired():
                detail += "  " + t("cli.profile.expired", date=cfg.expires_at)
        except ConfigError as exc:
            detail = t("cli.profile.unreadable", error=exc)
        _print(f"{'*' if ref.id == active else ' '} {ref.id:<24} {detail}")
    return 0


def _tunnel_in_use() -> str | None:
    """Who runs the tunnel right now, if anyone; switching profiles under it
    would leave it running on the profile the user just left."""
    from outwarp.ownership import TunnelOwnerLock, describe_owner

    if sys.platform == "linux":
        from outwarp.service import service_is_active

        if service_is_active():
            return t("cli.profile.background_service")
    lock = TunnelOwnerLock()
    if lock.acquire():
        lock.release()
        return None
    return describe_owner()


def _profile_use(profile_id: str) -> int:
    from outwarp import profiles

    if profile_id not in {p.id for p in profiles.list_profiles()}:
        _err(t("cli.profile.unknown", id=profile_id))
        return 1
    if profile_id == profiles.active_id():
        _print(t("cli.profile.already_active", id=profile_id))
        return 0
    owner = _tunnel_in_use()
    if owner:
        _err(t("cli.profile.in_use", owner=owner))
        return 1
    profiles.set_active(profile_id)
    _print(t("cli.profile.now_active", id=profile_id))
    return 0


def _profile_remove(profile_id: str, *, assume_yes: bool) -> int:
    from outwarp import profiles

    if profile_id not in {p.id for p in profiles.list_profiles()}:
        _err(t("cli.profile.unknown", id=profile_id))
        return 1
    if profile_id == profiles.active_id():
        owner = _tunnel_in_use()
        if owner:
            _err(t("cli.profile.active_in_use", id=profile_id, owner=owner))
            return 1
    if not assume_yes:
        answer = input(t("cli.profile.confirm_delete", id=profile_id))
        if answer.strip().lower() != "yes":
            _print(t("cli.aborted"))
            return 1
    now_active = profiles.remove(profile_id)
    _print(t("cli.profile.removed", id=profile_id)
           + (t("cli.profile.removed_active", id=now_active) if now_active
              else t("cli.profile.removed_none_left")))
    return 0


def _profile_show() -> int:
    config = _load_config()
    if config is None:
        return 1
    _print(t("cli.show.name", value=config.name or t("cli.unnamed")))
    _print(t("cli.show.endpoint", value=f"{config.server.endpoint}:{config.server.port}"))
    if config.tls.verify == "ca":
        _print(t("cli.show.tls_ca"))
    else:
        key = "cli.show.tls_key_pin" if config.tls.spki_sha256 else "cli.show.tls_cert_pin"
        _print(t(key, value=config.tls.pin_value))
    _print(t("cli.show.wg_name", value=config.wireguard.tunnel_name))
    _print(t("cli.show.wg_addr", value=config.wireguard.client_address))
    _print(t("cli.show.wg_mtu", value=config.wireguard.mtu))
    _print(t("cli.show.wg_dns", value=", ".join(config.wireguard.dns)))
    _print(t("cli.show.bypass",
             value=", ".join(config.routing.bypass_ips) or t("cli.none")))
    _print(t("cli.show.local_port", value=config.tunnel.local_port))
    _print(t("cli.show.remote",
             value=f"{config.tunnel.remote_host}:{config.tunnel.remote_port}"))
    _print(t("cli.show.attempts", value=config.reconnect.max_attempts))
    _print(t("cli.show.delays",
             value=", ".join(str(d) for d in config.reconnect.delays_seconds)))
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    path = default_log_path()
    if not path.exists():
        _print(t("cli.logs.none", path=path))
        return 0

    if not args.follow:
        try:
            sys.stdout.write(path.read_text(encoding="utf-8", errors="replace"))
            sys.stdout.flush()
        except OSError as exc:
            _err(t("cli.logs.read_error", path=path, error=exc))
            return 1
        return 0

    # tail -f style: seek to end, then poll for appends. Rotation (the file
    # being replaced) is handled by re-opening when the inode changes.
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _err(t("cli.logs.open_error", path=path, error=exc))
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
    """Remove the active profile and its baseline snapshot (`outwarp profile
    remove <id>` removes any profile).

    Does NOT touch the helper script, sudoers rule, autostart entry, or the
    pipx venv — for a full purge use ``outwarp uninstall`` instead.
    """
    cfg = default_config_path()
    baseline = original_config_path(cfg)

    if not cfg.exists() and not baseline.exists():
        _print(t("cli.forget.nothing"))
        return 0

    if not args.yes:
        _print(t("cli.forget.will_delete"))
        if cfg.exists():
            _print(f"  - {cfg}")
        if baseline.exists():
            _print(f"  - {baseline}")
        answer = input(t("cli.forget.confirm")).strip().lower()
        if answer != "yes":
            _print(t("cli.aborted"))
            return 1

    # Refuse to wipe the profile while a tunnel using it is still up. Otherwise
    # the WG service keeps running with config the user thinks they've deleted.
    if cfg.exists():
        try:
            config = ClientConfig.load(cfg)
            if get_platform().is_wg_tunnel_active(config.wireguard.tunnel_name):
                _err(t("cli.forget.tunnel_active", iface=config.wireguard.tunnel_name))
                return 1
        except (ConfigError, PlatformError) as exc:
            # Couldn't check — log and continue. Better to let the user delete
            # a corrupt profile than to wedge them out of cleanup.
            log.warning("Could not verify tunnel state before uninstall: %s", exc)

    from outwarp import profiles

    if cfg.parent.parent == profiles.profiles_dir():
        # The active profile of several: drop it and activate the next one.
        try:
            now_active = profiles.remove(cfg.parent.name)
        except (OSError, profiles.ProfileError) as exc:
            _err(t("cli.forget.remove_failed", path=cfg.parent, error=exc))
            return 1
        _print(t("cli.forget.removed")
               + (t("cli.forget.removed_active", id=now_active) if now_active else ""))
        return 0

    for path in (cfg, baseline):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _err(t("cli.forget.remove_failed", path=path, error=exc))
            return 1

    parent = cfg.parent
    if parent.exists():
        try:
            # Only rmdir if empty — preserves any sibling files the user added.
            if not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    _print(t("cli.forget.removed"))
    return 0


# ── Argparse plumbing ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outwarp",
        description=t("cli.help.description"),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_import = sub.add_parser("import", help=t("cli.help.import"))
    p_import.add_argument("path", help=t("cli.help.import_path"))

    p_connect = sub.add_parser(
        "connect",
        help=t("cli.help.connect"),
    )
    p_connect.add_argument(
        "--allow-tls-intercept",
        action="store_true",
        help=t("cli.help.allow_tls"),
    )

    # Headless background mode — the ExecStart= target for the systemd /
    # SCM unit. Same TunnelManager as `connect`, but silent on stdout so
    # the service journal stays readable.
    p_daemon = sub.add_parser(
        "daemon",
        help=t("cli.help.daemon"),
    )
    p_daemon.add_argument(
        "--allow-tls-intercept",
        action="store_true",
        help=t("cli.help.allow_tls_daemon"),
    )

    # `outwarp service install/uninstall/status` manages the systemd
    # user unit that drives `daemon`. On Windows this command stub-exits
    # and tells the user to use the installer's SCM registration.
    p_service = sub.add_parser(
        "service",
        help=t("cli.help.service"),
    )
    p_service.add_argument(
        "action",
        choices=("install", "uninstall", "status"),
        help=t("cli.help.service_action"),
    )

    sub.add_parser("status", help=t("cli.help.status"))
    p_profile = sub.add_parser(
        "profile", help=t("cli.help.profile"),
    )
    p_profile_sub = p_profile.add_subparsers(dest="profile_action", metavar="<action>")
    p_profile_sub.add_parser("show", help=t("cli.help.profile_show"))
    p_profile_sub.add_parser("list", help=t("cli.help.profile_list"))
    p_use = p_profile_sub.add_parser(
        "use", help=t("cli.help.profile_use"),
    )
    p_use.add_argument("id", help=t("cli.help.profile_id"))
    p_rm = p_profile_sub.add_parser("remove", help=t("cli.help.profile_remove"))
    p_rm.add_argument("id", help=t("cli.help.profile_id"))
    p_rm.add_argument("-y", "--yes", action="store_true", help=t("cli.help.yes"))

    p_logs = sub.add_parser("logs", help=t("cli.help.logs"))
    p_logs.add_argument(
        "-f", "--follow", action="store_true",
        help=t("cli.help.logs_follow"),
    )

    p_forget = sub.add_parser(
        "forget-profile",
        help=t("cli.help.forget"),
    )
    p_forget.add_argument("-y", "--yes", action="store_true", help=t("cli.help.yes"))

    p_un = sub.add_parser(
        "uninstall",
        help=t("cli.help.uninstall"),
    )
    p_un.add_argument("-y", "--yes", action="store_true", help=t("cli.help.yes"))

    sub.add_parser("doctor", help=t("cli.help.doctor"))

    # Internal: run by the installer's boot/logon scheduled task (Windows), not
    # part of the documented CLI: no help= keeps it out of the listing.
    sub.add_parser("recover-tunnel")

    sub.add_parser(
        "tui",
        help=t("cli.help.tui"),
    )

    p_gui = sub.add_parser(
        "gui",
        help=t("cli.help.gui"),
    )
    p_gui.add_argument(
        "--install", action="store_true",
        help=t("cli.help.gui_install"),
    )

    p_ui = sub.add_parser(
        "ui",
        help=t("cli.help.ui"),
    )
    p_ui.add_argument("choice", nargs="?", choices=["auto", "gui", "tui"])
    p_ui.add_argument(
        "--hyprland-rule", action="store_true",
        help=t("cli.help.hyprland_rule"),
    )

    sub.add_parser(
        "launch",
        help=t("cli.help.launch"),
    )

    p_update = sub.add_parser(
        "update",
        help=t("cli.help.update"),
    )
    p_update.add_argument(
        "--check-only",
        action="store_true",
        help=t("cli.help.update_check"),
    )

    return parser


def _cmd_tui(args: argparse.Namespace) -> int:
    try:
        from outwarp.tui.app import OutWarpClientTUI
    except ImportError as exc:
        _err(t("cli.tui.missing", error=exc))
        return 1
    return OutWarpClientTUI().run() or 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from outwarp.diagnostics import Status, run_all
    results = run_all()
    for r in results:
        icon = {"pass": "✓", "warn": "⚠", "fail": "✗", "skip": "—"}.get(r.status.value, "?")
        _print(f"  {icon}  {r.name:<40} {r.detail or ''}")
        if r.remediation:
            _print(f"        → {r.remediation}")
    return 1 if any(r.status == Status.FAIL for r in results) else 0


def _cmd_gui(args: argparse.Namespace) -> int:
    """Delegate to outwarp.app:main — the pywebview tray entry-point.

    Was the dedicated ``outwarp`` binary in 0.4.x; collapsed into a subcommand
    in 0.5.0 so the Linux install surface is a single executable. On Linux
    the GUI stack is optional: ``--install`` adds it, and launching without it
    says so before falling back to the TUI instead of doing it silently.
    """
    from outwarp import ui_choice

    if getattr(args, "install", False):
        if sys.platform == "linux" and os.geteuid() != 0:
            _err(t("cli.gui.need_root", hint=ui_choice.INSTALL_HINT))
            return 2
        return ui_choice.install_gui(echo=_print)

    if sys.platform == "linux":
        ok, why = ui_choice.gui_available()
        if not ok:
            _err(t("cli.gui.unavailable", why=why))
            return _cmd_tui(args)
    from outwarp.app import main as _gui_main
    return _gui_main() or 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from outwarp import ui_choice

    if args.choice:
        ui_choice.set_preferred_ui(args.choice)
        _print(t("cli.ui.set", choice=args.choice))
    ok, why = ui_choice.gui_available()
    pref = ui_choice.preferred_ui()
    _print(t("cli.ui.preferred", value=pref))
    _print(t("cli.ui.stack",
             state=t("cli.ui.stack_available" if ok else "cli.ui.stack_missing"), why=why))
    _print(t("cli.ui.launch_opens", value=ui_choice.resolve_ui(available=ok)))
    if not ok and sys.platform == "linux":
        _print(t("cli.ui.add_gui", hint=ui_choice.INSTALL_HINT))
    if sys.platform == "linux":
        from outwarp import desktop_linux as dl

        tray_state, tray_detail = dl.tray_status()
        if tray_state != "skip":
            _print(t("cli.ui.tray",
                     state="ok" if tray_state == "ok" else t("cli.ui.tray_warn"),
                     detail=tray_detail))
        if getattr(args, "hyprland_rule", False):
            try:
                _print(t("cli.ui.hypr_installed_now", detail=dl.install_hyprland_rule()))
            except OSError as exc:
                _err(t("cli.ui.hypr_rule_failed", error=exc))
                return 1
        elif dl.is_hyprland():
            if dl.hyprland_rule_installed():
                _print(t("cli.ui.hypr_rule_present"))
            else:
                _print(t("cli.ui.hypr_rule_absent"))
    return 0


def _cmd_launch(args: argparse.Namespace) -> int:
    """What the .desktop entry runs: pick the UI, and give the TUI a terminal
    when there is none (launchers start us without a tty)."""
    from outwarp import ui_choice

    if ui_choice.resolve_ui() == "gui":
        from outwarp.app import main as _gui_main
        return _gui_main() or 0
    if sys.stdin.isatty():
        return _cmd_tui(args)
    if sys.platform == "win32":
        return _cmd_tui(args)
    tui_argv = [sys.argv[0], "tui"] if sys.argv else ["outwarp", "tui"]
    cmd = ui_choice.terminal_command(tui_argv)
    if cmd is None:
        _err(t("cli.launch.no_terminal"))
        return 1
    return subprocess.call(cmd)


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
    ``sudo outwarp update``).
    """
    import contextlib
    import tempfile

    from outwarp.updater import (
        apply_linux_update,
        check_for_linux_update,
        download_installer,
        verify_download,
    )

    _print(t("cli.update.checking", version=__version__))
    info = check_for_linux_update(__version__, "client")

    if info.get("error"):
        _err(t("cli.update.check_failed", error=info["error"]))
        return 1

    if not info.get("available"):
        latest = info.get("latest") or __version__
        # If a newer tag exists but the release has no Linux wheel attached
        # (e.g. an older Windows-only release), say so explicitly rather than
        # claiming we're already on the latest version.
        from outwarp.updater import _is_newer as _newer
        if latest and _newer(latest, __version__) and not info.get("wheel_url"):
            _print(t("cli.update.no_wheel", latest=latest))
            _print(t("cli.update.see", url=info.get("html_url", "")))
        else:
            _print(t("cli.update.up_to_date", latest=latest))
        return 0

    latest = info["latest"]
    _print(t("cli.update.available", latest=latest))
    _print(t("cli.update.release", url=info.get("html_url", "")))

    if args.check_only:
        _print(t("cli.update.run_hint"))
        return 0

    wheel_url = info.get("wheel_url", "")
    wheel_name = info.get("wheel_name") or Path(wheel_url).name
    if not wheel_url:
        _err(t("cli.update.no_wheel_in", latest=latest, url=info.get("html_url", "")))
        return 1

    # ``geteuid`` is POSIX-only but the client is shipped only on Linux for
    # the Python wheel flow, so anchor the gate on the platform explicitly.
    # On Windows the installer ships the GUI wheel separately and there's no
    # ``outwarp update`` flow yet.
    if sys.platform == "linux" and os.geteuid() != 0:
        _err(t("cli.update.need_root"))
        return 1

    tmp_dir = Path(tempfile.mkdtemp())
    wheel_path = tmp_dir / wheel_name

    try:
        _print(t("cli.update.downloading", name=wheel_name))
        last_milestone = [-1]

        def _progress(pct: int) -> None:
            milestone = pct // 20
            if milestone > last_milestone[0]:
                last_milestone[0] = milestone
                _print(f"  {pct}%")

        try:
            download_installer(wheel_url, wheel_path, _progress)
        except Exception as exc:
            _err(t("cli.update.download_failed", error=exc))
            return 1

        ok, detail = verify_download(
            wheel_path, wheel_name,
            info.get("checksums_url", ""), info.get("signature_url", ""),
        )
        if not ok:
            _err(t("cli.update.integrity_failed", detail=detail))
            return 1
        _print(f"  {detail}")

        _print(t("cli.update.installing"))
        try:
            apply_linux_update(wheel_path, extras="tui")
        except subprocess.TimeoutExpired:
            _err(t("cli.update.pip_timeout"))
            return 1
        except Exception as exc:
            _err(t("cli.update.pip_failed", error=exc))
            return 1

        _print("\n" + t("cli.update.updated", latest=latest))
        _print(t("cli.update.restart"))
        return 0
    finally:
        with contextlib.suppress(OSError):
            wheel_path.unlink(missing_ok=True)
            tmp_dir.rmdir()


def _cmd_daemon(args: argparse.Namespace) -> int:
    from outwarp.service import run_daemon
    return run_daemon(allow_tls_intercept=args.allow_tls_intercept)


def _cmd_recover_tunnel(args: argparse.Namespace) -> int:
    """Remove a tunnel an unclean shutdown left behind (B-034).

    Runs as SYSTEM at boot and at every logon, before or alongside the tray
    app: a tunnel service still installed while no OutWarp process could own
    it routes everything into an adapter with no wstunnel under it.
    """
    setup_logging()
    from outwarp.platforms import get_platform

    platform = get_platform()
    if platform.tunnel_owner_running():
        log.info("recover-tunnel: an OutWarp tunnel owner is running; nothing to do")
        return 0
    removed = platform.remove_stale_tunnels()
    if removed:
        log.warning("recover-tunnel: removed stale tunnel(s): %s", ", ".join(removed))
        _print(t("cli.recover.removed", names=", ".join(removed)))
    return 0


def _cmd_service(args: argparse.Namespace) -> int:
    from outwarp.service import install_service, service_status, uninstall_service
    if args.action == "install":
        return install_service()
    if args.action == "uninstall":
        return uninstall_service()
    return service_status()


_COMMANDS = {
    "import":         _cmd_import,
    "connect":        _cmd_connect,
    "daemon":         _cmd_daemon,
    "service":        _cmd_service,
    "status":         _cmd_status,
    "profile":        _cmd_profile,
    "logs":           _cmd_logs,
    "forget-profile": _cmd_forget_profile,
    "uninstall":      _cmd_uninstall,
    "doctor":         _cmd_doctor,
    "recover-tunnel": _cmd_recover_tunnel,
    "tui":            _cmd_tui,
    "gui":            _cmd_gui,
    "ui":             _cmd_ui,
    "launch":         _cmd_launch,
    "update":         _cmd_update,
}


def main_legacy_alias(argv: list[str] | None = None) -> int:
    """``outwarp-cli`` — the pre-1.0 command name, kept one release as an alias.

    Behaves exactly like ``outwarp`` (same parser, same exit codes) and prints
    a single stderr line so scripts and units still pointing at the old name
    keep working while their owners notice. Removed in 1.0.0.
    """
    _err(t("cli.deprecated_alias"))
    return main(argv)


def _launch_windows_gui() -> int:
    """Bare `outwarp` on Windows opens the app, as it did before 0.15.0.

    Since then `outwarp.exe` is the console CLI and the GUI is
    `outwarp-gui.exe` (B-027). Shortcuts and autostart entries written by older
    versions still point at `outwarp.exe` with no arguments; hand them over to
    the GUI next to it instead of printing usage into a console that closes.
    """
    if getattr(sys, "frozen", False):
        gui = Path(sys.executable).with_name("outwarp-gui.exe")
        if gui.exists():
            os.startfile(gui)  # type: ignore[attr-defined]  # ShellExecute honours its UAC manifest
            return 0
    from outwarp.app import main as gui_main

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    if sys.platform == "win32" and not (sys.argv[1:] if argv is None else argv):
        return _launch_windows_gui()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args)
    except TunnelError as exc:
        _err(t("cli.tunnel_error", error=exc))
        return 1
    except KeyboardInterrupt:
        _err(t("cli.interrupted"))
        return 130
