from __future__ import annotations

import argparse
import contextlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from outwarp_server import __version__
from outwarp_server.config import (
    CONFIG_DIR_ENV,
    ConfigError,
    ServerConfig,
    default_config_dir,
    default_config_path,
)
from outwarp_server.i18n import t
from outwarp_server.wireguard import get_live_peers

log = logging.getLogger(__name__)
console = Console()


# Commands that read/modify privileged state (systemd, /etc/wireguard, wg interface).
# Anything not in this set runs without a root check (--version, --help).
_PRIVILEGED_COMMANDS = frozenset({
    "setup", "add-client", "list-clients", "revoke-client", "rotate-client",
    "disable-client", "enable-client",
    "renew-cert", "prune-expired", "status", "restart", "uninstall", "doctor",
    "init", "serve", "tui",
    "web", "admin-token", "enroll-listener",
})
# ``gui`` is intentionally NOT in the privileged set: the pywebview shell is
# safe to launch as the invoking user, and the underlying API enforces root
# on each privileged call itself.
# ``update`` is intentionally NOT in the privileged set: ``--check-only`` is a
# read-only network call that anyone should be able to run, and ``_cmd_update``
# enforces root itself just before the pip-install step. Mirrors the client's
# ``outwarp update`` flow.


def _require_root(command: str) -> None:
    """Exit with a friendly error if the current user can't run privileged ops."""
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                return
        except Exception:
            return
        console.print(t("sv.need_admin", command=command))
        raise SystemExit(1)

    if os.geteuid() == 0:
        return
    console.print(t("sv.need_root", command=command))
    raise SystemExit(1)


def _resolve_config_path(args: argparse.Namespace) -> Path:
    if args.config_dir:
        return Path(args.config_dir) / "server_config.json"
    return default_config_path()


def _load_config(args: argparse.Namespace) -> ServerConfig:
    path = _resolve_config_path(args)
    try:
        return ServerConfig.load(path)
    except ConfigError as exc:
        console.print(t("sv.error", error=exc))
        console.print(t("sv.run_setup_first"))
        raise SystemExit(1) from exc


def _cmd_setup(args: argparse.Namespace) -> int:
    from outwarp_server.setup_wizard import run_setup

    config_dir = Path(args.config_dir) if args.config_dir else default_config_dir()
    return run_setup(config_dir)


def _cmd_init(args: argparse.Namespace) -> int:
    """Non-interactive init for Docker/Kubernetes — reads config from env vars."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from outwarp_server.k8s_init import run_init

    config_dir = Path(args.config_dir) if args.config_dir else default_config_dir()
    return run_init(config_dir)


# `serve` exit status when the manager ends up in ERROR (wstunnel died,
# WireGuard would not come up, prerequisites missing). Non-zero so the
# container runtime's restart policy takes over instead of a process that
# looks alive to Docker/kubelet while nothing is listening.
EXIT_SERVER_ERROR = 3


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the server in foreground — intended for Docker/Kubernetes.

    Loads server_config.json, starts wstunnel + WireGuard via ServerManager,
    and blocks until SIGTERM or SIGINT — or until the manager reports ERROR,
    which used to leave the process blocking forever with the tunnel down
    and only a liveness probe (if one matched the port) to notice.
    """
    import signal
    import threading

    from outwarp_server.logs import add_file_log, serve_log_path
    from outwarp_server.server_manager import ServerManager, ServerState

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        add_file_log(serve_log_path(_config_dir_from_args(args)))
    except OSError as exc:
        log.warning("serve: cannot write the log file for the web panel: %s", exc)

    config = _load_config(args)
    manager = ServerManager(config, config_path=_resolve_config_path(args))
    stop_event = threading.Event()
    failed = threading.Event()

    def _on_state(state: ServerState) -> None:
        log.info("Server state: %s", state.value)
        if state is ServerState.ERROR:
            log.error("Server entered ERROR — exiting so the supervisor can restart it")
            failed.set()
            stop_event.set()

    manager.add_listener(_on_state)
    manager.start()

    # SIGHUP = reload: `outwarp-server restart` run inside the container
    # (docker exec / kubectl exec) sends it, since this process is the only
    # one that owns wstunnel and the enrolment listener (B-030). The handler
    # only flags; the reload runs here, outside signal context.
    reload_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, lambda *_: reload_event.set())

    log.info("OutWarp server running. Send SIGTERM or Ctrl+C to stop, SIGHUP to reload.")
    while not stop_event.wait(0.5):
        if reload_event.is_set():
            reload_event.clear()
            log.info("SIGHUP: reloading the configuration and restarting the transport")
            try:
                manager.refresh_config()
                manager.restart()
            except Exception:
                log.exception("reload failed")

    log.info("Shutting down...")
    manager.stop()
    log.info("Done.")
    return EXIT_SERVER_ERROR if failed.is_set() else 0


def _cmd_enroll_listener(args: argparse.Namespace) -> int:
    """Run the enrolment listener in the foreground — the ExecStart= of
    ``outwarp-enroll.service`` on a native Linux install.

    Everywhere a ServerManager process keeps the transport up (Windows, Docker,
    Kubernetes, the desktop GUI) the listener is hosted in-process and this
    command is never needed; a systemd install only leaves units behind, so the
    listener gets one of its own. Blocks until SIGTERM or SIGINT.
    """
    import signal
    import threading

    from outwarp_server import enroll_server

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = _load_config(args)
    httpd = enroll_server.serve(config, _resolve_config_path(args))

    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    stop_event.wait()

    httpd.shutdown()
    httpd.server_close()
    return 0


def _expiry_from_days(days: int | None) -> str:
    """Turn a --days count into an ISO expiry date, or '' for no expiry."""
    if not days:
        return ""
    import datetime

    if days < 1:
        raise ValueError(t("sv.days_positive"))
    return (
        datetime.datetime.now(datetime.UTC).date()
        + datetime.timedelta(days=days)
    ).isoformat()


def _cmd_add_client(args: argparse.Namespace) -> int:
    from outwarp_server import operations

    config = _load_config(args)
    name = args.name

    try:
        expires_at = _expiry_from_days(getattr(args, "days", None))
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    enroll = not args.embed_key
    try:
        result = operations.add_client(
            config,
            name,
            config_path=_resolve_config_path(args),
            expires_at=expires_at,
            enroll=enroll,
            enroll_ttl_seconds=max(1, args.enroll_ttl) * 60 if enroll else 0,
        )
    except ValueError as exc:
        console.print(t("sv.error", error=exc))
        return 1
    except Exception as exc:
        console.print(t("sv.add.failed", error=exc))
        return 1

    console.print("\n" + t("sv.add.ok", name=name))
    console.print(t("sv.add.ip", ip=result.client.address))
    if result.client.psk:
        console.print(t("sv.add.psk"))
    if expires_at:
        console.print(t("sv.add.expires", date=expires_at))
    console.print(t("sv.add.config", path=result.owcfg_path))

    if enroll:
        import datetime as _dt
        deadline = _dt.datetime.fromtimestamp(
            result.enrollment_expires_at, _dt.UTC
        ).strftime("%H:%M UTC")
        console.print("\n" + t(
            "sv.add.enroll_note",
            server=f"{result.config.endpoint}:{result.config.port}",
            deadline=deadline, minutes=args.enroll_ttl,
        ))
    else:
        console.print("\n" + t("sv.add.embed_note"))
    return 0


def _cmd_prune_expired(args: argparse.Namespace) -> int:
    import datetime

    config = _load_config(args)
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    expired = [c for c in config.clients if c.expires_at and c.expires_at < today]

    if not expired:
        console.print(t("sv.prune.none"))
        return 0

    console.print(t("sv.prune.header"))
    for c in expired:
        console.print(t("sv.prune.item", name=c.name, date=c.expires_at))

    if not args.yes:
        answer = console.input("\n" + t("sv.prune.confirm"))
        if answer.strip().lower() != "yes":
            console.print(t("sv.aborted"))
            return 1

    from outwarp_server import operations

    config_path = _resolve_config_path(args)
    for c in expired:
        # Already gone (e.g. revoked concurrently) — nothing left to prune.
        with contextlib.suppress(KeyError):
            operations.revoke_client(config, c.name, config_path=config_path)

    console.print("\n" + t("sv.prune.done", count=len(expired)))
    return 0


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        f /= 1024
        if f < 1024:
            return f"{f:.1f} {u}"
    return f"{f:.1f} PB"


def _format_seconds_ago(seconds: int) -> str:
    if seconds < 60:
        return t("sv.ago", value=f"{seconds}s")
    if seconds < 3600:
        return t("sv.ago", value=f"{seconds // 60}m {seconds % 60}s")
    if seconds < 86400:
        return t("sv.ago", value=f"{seconds // 3600}h {(seconds % 3600) // 60}m")
    return t("sv.ago", value=f"{seconds // 86400}d {(seconds % 86400) // 3600}h")


# A peer is considered "online" if its last handshake is within this window.
# WireGuard renews handshakes roughly every 2 minutes; 3 minutes leaves margin.
_ONLINE_WINDOW_SECONDS = 180


def _pending_enrollments(config_dir: Path) -> list:
    from outwarp_server import enrollment
    try:
        return enrollment.pending(config_dir)
    except Exception:
        log.debug("Could not read the enrolment token store", exc_info=True)
        return []


def _cmd_list_clients(args: argparse.Namespace) -> int:
    import datetime
    import time

    config = _load_config(args)

    if not config.clients:
        console.print(t("sv.list.none"))
        return 0

    live_peers = get_live_peers()
    now = int(time.time())

    today = datetime.datetime.now(datetime.UTC).date().isoformat()

    table = Table(title=t("sv.list.title"))
    table.add_column(t("sv.list.col.name"), style="bold")
    table.add_column(t("sv.list.col.address"))
    table.add_column(t("sv.list.col.status"))
    table.add_column(t("sv.list.col.handshake"))
    table.add_column(t("sv.list.col.endpoint"))
    table.add_column(t("sv.list.col.transfer"))
    table.add_column(t("sv.list.col.expires"))
    never = t("sv.never")

    pending_names = {
        p.client_name for p in _pending_enrollments(_resolve_config_path(args).parent)
    }

    for c in config.clients:
        if c.state == "disabled":
            table.add_row(
                c.name, c.address, t("sv.status.disabled"), "[dim]—[/dim]",
                "[dim]—[/dim]", "[dim]—[/dim]", c.expires_at or never,
            )
            continue
        if not c.public_key:
            # Slot reserved by add-client, not yet claimed by the client. Showing
            # it as "unknown" would read as a broken peer rather than a normal
            # waiting state.
            state = (
                t("sv.status.awaiting") if c.name in pending_names
                else t("sv.status.enroll_expired")
            )
            table.add_row(
                c.name, c.address, state, "[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]",
                c.expires_at or never,
            )
            continue
        live = live_peers.get(c.public_key)
        if live is None:
            # Peer not even known to running WG (interface down, or peer not synced)
            status = t("sv.status.unknown")
            handshake = "[dim]—[/dim]"
            endpoint = "[dim]—[/dim]"
            transfer = "[dim]—[/dim]"
        elif live.latest_handshake is None:
            status = t("sv.status.idle")
            handshake = never
            endpoint = "[dim]—[/dim]"
            transfer = "0 B / 0 B"
        else:
            seconds_ago = now - live.latest_handshake
            if seconds_ago < _ONLINE_WINDOW_SECONDS:
                status = t("sv.status.online")
            else:
                status = t("sv.status.offline")
            handshake = _format_seconds_ago(seconds_ago)
            endpoint = live.endpoint or "[dim]—[/dim]"
            transfer = f"{_format_bytes(live.transfer_rx)} / {_format_bytes(live.transfer_tx)}"

        if not c.expires_at:
            expires = never
        elif c.expires_at < today:
            expires = t("sv.list.expired", date=c.expires_at)
        else:
            expires = c.expires_at

        table.add_row(c.name, c.address, status, handshake, endpoint, transfer, expires)

    console.print(table)
    return 0


def _cmd_revoke_client(args: argparse.Namespace) -> int:
    from outwarp_server import operations

    config = _load_config(args)
    name = args.name

    try:
        operations.revoke_client(
            config, name, config_path=_resolve_config_path(args)
        )
    except KeyError as exc:
        console.print(t("sv.error", error=exc.args[0] if exc.args else exc))
        return 1

    console.print(t("sv.revoke.ok", name=name))
    return 0


def _set_client_enabled(args: argparse.Namespace, enabled: bool) -> int:
    from outwarp_server import operations

    config = _load_config(args)
    try:
        result = operations.set_client_enabled(
            config, args.name, enabled, config_path=_resolve_config_path(args)
        )
    except KeyError as exc:
        console.print(t("sv.error", error=exc.args[0] if exc.args else exc))
        return 1

    if enabled:
        console.print(t("sv.enable.ok", name=args.name))
    else:
        console.print(t("sv.disable.ok", name=args.name))
    if not result.hot_applied:
        console.print(t("sv.wg_not_running"))
    if result.wg_persist_warning:
        console.print(t("sv.wg_write_failed", warning=result.wg_persist_warning))
    return 0


def _cmd_disable_client(args: argparse.Namespace) -> int:
    return _set_client_enabled(args, False)


def _cmd_enable_client(args: argparse.Namespace) -> int:
    return _set_client_enabled(args, True)


def _cmd_rotate_client(args: argparse.Namespace) -> int:
    """Generate a new WireGuard keypair + PSK for an existing client.

    The client's IP address and expiry are preserved. A new .owcfg is written to
    the current directory — it must be re-distributed to the client, as the old
    one becomes invalid immediately.
    """
    from outwarp_server import operations

    config = _load_config(args)

    try:
        result = operations.rotate_client(
            config,
            args.name,
            config_path=_resolve_config_path(args),
        )
    except ValueError as exc:
        console.print(t("sv.error", error=exc))
        return 1
    except Exception as exc:
        console.print(t("sv.rotate.failed", error=exc))
        return 1

    console.print("\n" + t("sv.rotate.ok", name=args.name))
    console.print(t("sv.rotate.pubkey", value=f"{result.client.public_key[:24]}…"))
    console.print(t("sv.rotate.owcfg", path=result.owcfg_path))
    console.print(t("sv.rotate.sha", value=f"{result.owcfg_sha256[:23]}…"))
    if result.wg_persist_warning:
        console.print(t("sv.rotate.warning", warning=result.wg_persist_warning))
    if not result.hot_rotated:
        console.print(t("sv.rotate.restart_note"))
    console.print("\n" + t("sv.rotate.send"))
    return 0


def _cmd_renew_cert(args: argparse.Namespace) -> int:
    """Reissue the self-signed TLS certificate before it expires.

    The private key is reused unless --new-key is passed, which is what keeps
    this non-breaking: clients pin the key (``tls.spki_sha256``), not the
    certificate, so they never notice the swap. Profiles issued by an OutWarp
    older than the key pin, or issued with --new-key, do have to be re-created.
    """
    from dataclasses import replace

    from outwarp_server.crypto import CryptoError, generate_tls_cert, renew_tls_cert

    config = _load_config(args)
    cert_path, key_path = Path(config.cert_path), Path(config.key_path)

    try:
        if args.new_key:
            _, _, fingerprint, spki = generate_tls_cert(
                config.endpoint, cert_path.parent, cert_path.name, key_path.name
            )
        else:
            fingerprint, spki = renew_tls_cert(cert_path, key_path, config.endpoint)
    except (CryptoError, OSError) as exc:
        console.print(t("sv.cert.failed", error=exc))
        return 1

    updated = replace(config, cert_fingerprint_sha256=fingerprint, spki_sha256=spki)
    try:
        updated.save(_resolve_config_path(args))
    except OSError as exc:
        console.print(t("sv.cert.save_failed", error=exc))
        return 1

    console.print("\n" + t("sv.cert.ok"))
    console.print(t("sv.cert.fingerprint", value=f"{fingerprint[:23]}…"))
    console.print(t("sv.cert.keypin", value=f"{spki[:23]}…"))
    if args.new_key:
        console.print("\n" + t("sv.cert.new_key_note"))
    else:
        console.print("\n" + t("sv.cert.reused_note"), style="dim")
    console.print("\n" + t("sv.cert.restart"))
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    """Regenerate wg0.conf from current config and fully restart wg-quick + wstunnel.

    Use this after upgrading OutWarp or whenever PostUp/PostDown rules change —
    a hot reload (wg syncconf) does NOT re-run those scripts.
    """
    from outwarp_server import operations

    config = _load_config(args)

    console.print(t("sv.restart.regenerating"))
    result = operations.restart_services(config, config_path=_resolve_config_path(args))

    if result.wg_conf_written:
        console.print(t("sv.restart.conf_written"))
    else:
        # The first error in restart_services always belongs to "WireGuard config".
        msg = result.errors[0] if result.errors else t("sv.restart.conf_failed")
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print(t("sv.restart.wg"))
    if result.wg_restarted:
        console.print(t("sv.restart.wg_ok"))
    else:
        msg = result.errors[0] if result.errors else t("sv.restart.wg_failed")
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    if result.transport_note:
        console.print(f"  [yellow]![/yellow] {result.transport_note}")
        console.print("\n" + t("sv.restart.wg_done"))
        return 0

    console.print(t("sv.restart.wstunnel"))
    if result.wstunnel_restarted:
        console.print(t("sv.restart.wstunnel_ok"))
    else:
        msg = next(
            (e for e in result.errors if e.startswith("wstunnel")),
            t("sv.restart.wstunnel_failed"),
        )
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print(t("sv.restart.enroll"))
    if result.enroll_restarted:
        console.print(t("sv.restart.enroll_ok"))
    else:
        msg = next(
            (e for e in result.errors if e.startswith("enrolment")),
            t("sv.restart.enroll_failed"),
        )
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print("\n" + t("sv.restart.done"))
    return 0


def _spawn_deferred_cleanup(install_prefix: Path, bin_link: Path | None) -> None:
    """Spawn a detached shell script that removes paths AFTER this process exits.

    Necessary because the running Python interpreter lives inside install_prefix
    (e.g. /opt/outwarp-server/.venv) — we can't rmtree the dir we're executing
    from. The script polls for our PID to disappear, then deletes itself last.
    """
    import os
    import shlex
    import subprocess
    import tempfile

    pid = os.getpid()
    targets = [str(install_prefix)]
    if bin_link is not None:
        targets.append(str(bin_link))

    # Build rm commands: -rf for the prefix (directory), -f for the symlink.
    rm_lines = [f"rm -rf {shlex.quote(str(install_prefix))}"]
    if bin_link is not None:
        rm_lines.append(f"rm -f {shlex.quote(str(bin_link))}")

    script = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
        "sleep 1\n"
        + "\n".join(rm_lines)
        + "\nrm -f \"$0\"\n"
    )
    fd, script_path = tempfile.mkstemp(prefix="outwarp-uninstall-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    os.chmod(script_path, 0o755)
    subprocess.Popen(
        ["/bin/bash", script_path],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _legacy_artifacts(install_prefix: Path | None) -> list[Path]:
    """Stray paths from earlier installs that aren't the running interpreter's
    prefix — safe to remove synchronously. Covers in-place upgrades where both
    layouts coexist (pipx + legacy /opt/outwarp-server) and the 0.4.x
    ``outwarp-server-gui`` shim that 0.5.0 collapsed into ``server gui``."""
    if sys.platform != "linux":
        return []
    candidates = [
        Path("/opt/pipx/venvs/outwarp-server"),
        Path("/opt/outwarp-server"),
        Path("/usr/local/bin/outwarp-server-gui"),
    ]
    return [
        p for p in candidates
        if p.exists() and (install_prefix is None or p != install_prefix)
    ]


def _cmd_uninstall(args: argparse.Namespace) -> int:
    from outwarp_server.platforms import PlatformError, get_server_platform

    config_path = _resolve_config_path(args)
    config_dir = config_path.parent
    platform = get_server_platform()
    install_prefix = platform.install_prefix()
    bin_link = platform.bin_link()
    legacy = _legacy_artifacts(install_prefix)

    console.print(t("sv.un.warning"))
    console.print(t("sv.un.services"))
    console.print(t("sv.un.wireguard"))
    console.print(t("sv.un.config", path=config_dir))
    console.print(t("sv.un.sysctl"))
    if install_prefix is not None:
        console.print(t("sv.un.prefix", path=install_prefix))
    if bin_link is not None:
        console.print(t("sv.un.symlink", path=bin_link))
    for path in legacy:
        console.print(t("sv.un.stray", path=path))

    if not args.yes:
        answer = console.input("\n" + t("sv.un.confirm"))
        if answer.strip().lower() != "yes":
            console.print(t("sv.aborted"))
            return 1

    warnings: list[str] = []

    def _step(label: str, fn: callable) -> None:
        console.print(f"  {label}...", end=" ")
        try:
            fn()
            console.print(t("sv.un.done"))
        except (PlatformError, OSError) as exc:
            console.print(t("sv.un.warn", error=exc))
            warnings.append(f"{label}: {exc}")

    console.print()
    _step(t("sv.un.step.wstunnel"), platform.uninstall_wstunnel_service)
    _step(t("sv.un.step.enroll"), platform.uninstall_enroll_service)
    _step(t("sv.un.step.wg"), platform.uninstall_wg_config)

    def _rm_caddy_front() -> None:
        # Only OutWarp's own conf.d file. The main Caddyfile and any other site
        # on this box are not ours to touch.
        from outwarp_server import caddy
        if not caddy.CADDY_SITE_FILE.exists():
            return
        try:
            caddy.remove()
        except caddy.CaddyError as exc:
            # _step only reports PlatformError/OSError; a failed cleanup here
            # should degrade to a warning like every other step, not abort the
            # uninstall halfway through.
            raise PlatformError(str(exc)) from exc

    _step(t("sv.un.step.caddy"), _rm_caddy_front)

    def _rm_config_dir() -> None:
        import shutil
        if config_dir.exists():
            shutil.rmtree(config_dir)

    _step(t("sv.un.step.config", path=config_dir), _rm_config_dir)

    # Strays first — they can't be the running interpreter's tree (we filtered
    # install_prefix out of the candidates), so unlinking is safe right now.
    for path in legacy:
        def _rm(p: Path = path) -> None:
            import shutil
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        _step(t("sv.un.step.stray", path=path), _rm)

    # Defer venv + symlink removal until after we exit (we live inside install_prefix).
    if install_prefix is not None and install_prefix.exists():
        try:
            _spawn_deferred_cleanup(install_prefix, bin_link)
            console.print(t(
                "sv.un.scheduled",
                paths=str(install_prefix) + (f" {t('sv.and')} {bin_link}" if bin_link else ""),
            ))
        except OSError as exc:
            console.print(t("sv.un.schedule_failed", error=exc))
            warnings.append(f"{t('sv.un.deferred')}: {exc}")
    elif bin_link is not None and bin_link.exists():
        # No install prefix to remove (e.g., dev install) — just unlink the binary.
        _step(t("sv.un.step.symlink", path=bin_link), lambda: bin_link.unlink())

    if warnings:
        console.print("\n" + t("sv.un.finished_warnings", count=len(warnings)))
        return 1

    console.print("\n" + t("sv.un.success"))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from outwarp_server.platforms import PlatformError, get_server_platform

    config = _load_config(args)
    platform = get_server_platform()

    try:
        wstunnel_active = platform.is_wstunnel_running()
    except PlatformError as exc:
        wstunnel_active = None
        wstunnel_error = str(exc)
    else:
        wstunnel_error = None

    try:
        wg_active = platform.is_wg_active()
    except PlatformError as exc:
        wg_active = None
        wg_error = str(exc)
    else:
        wg_error = None

    table = Table(title=t("sv.status.title"), show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row(t("sv.status.endpoint"), f"{config.endpoint}:{config.port}")
    table.add_row(t("sv.status.subnet"), config.subnet)
    table.add_row(t("sv.status.wg_address"), config.server_address)
    table.add_row(t("sv.status.wg_port"), str(config.wg_listen_port))
    table.add_row(t("sv.status.clients"), str(len(config.clients)))

    def _status_cell(active: bool | None, error: str | None) -> str:
        if active is True:
            return t("sv.status.running")
        if active is False:
            return t("sv.status.stopped")
        return t("sv.status.unknown_error", error=error)

    table.add_row(t("sv.status.wstunnel"), _status_cell(wstunnel_active, wstunnel_error))
    table.add_row(t("sv.status.wg_iface"), _status_cell(wg_active, wg_error))
    if platform.manages_enroll_service:
        # Only a native systemd install has a listener of its own to report;
        # everywhere else it lives inside the `serve`/GUI process.
        table.add_row(
            t("sv.status.enroll"),
            t("sv.status.running") if platform.is_enroll_running() else t("sv.status.stopped"),
        )

    console.print(table)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Run the diagnostics battery and print a pass/warn/fail report.

    Exit code: 0 if no failures, 1 if any FAIL (WARN does not fail the run —
    warnings often signal "works for now but fragile" and shouldn't block CI).
    """
    from rich.panel import Panel

    from outwarp_server.diagnostics import Status, run_all

    config = _load_config(args)

    console.print(
        Panel(
            t("sv.doctor.panel"),
            border_style="cyan",
        )
    )

    results = run_all(config)

    table = Table(title=t("sv.doctor.results"), show_lines=False)
    table.add_column("", width=2)
    table.add_column(t("sv.doctor.check"), style="bold")
    table.add_column(t("sv.doctor.detail"))

    icons = {
        Status.PASS: "[green]✓[/green]",
        Status.WARN: "[yellow]⚠[/yellow]",
        Status.FAIL: "[red]✗[/red]",
        Status.SKIP: "[dim]—[/dim]",
    }
    for r in results:
        table.add_row(icons[r.status], r.name, r.detail or "")
    console.print(table)

    needs_action = [r for r in results if r.status in (Status.FAIL, Status.WARN) and r.remediation]
    if needs_action:
        console.print("\n" + t("sv.doctor.actions"))
        for r in needs_action:
            style = "red" if r.status == Status.FAIL else "yellow"
            console.print(f"  [{style}]•[/{style}] [bold]{r.name}[/bold]: {r.remediation}")

    summary = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 0, Status.SKIP: 0}
    for r in results:
        summary[r.status] += 1
    console.print("\n" + t(
        "sv.doctor.summary",
        ok=summary[Status.PASS], warn=summary[Status.WARN], fail=summary[Status.FAIL],
    ))
    return 1 if summary[Status.FAIL] > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outwarp-server",
        description=t("sv.help.description"),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help=t("sv.help.config_dir"),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help=t("sv.help.setup"))

    sub.add_parser(
        "init",
        help=t("sv.help.init"),
    )

    sub.add_parser(
        "serve",
        help=t("sv.help.serve"),
    )

    sub.add_parser(
        "enroll-listener",
        help=t("sv.help.enroll_listener"),
    )

    p_add = sub.add_parser("add-client", help=t("sv.help.add_client"))
    p_add.add_argument("name", help=t("sv.help.add_name"))
    p_add.add_argument(
        "--days", type=int, default=None,
        help=t("sv.help.add_days"),
    )
    p_add.add_argument(
        "--enroll-ttl", type=int, default=15, metavar="MIN",
        help=t("sv.help.add_ttl"),
    )
    p_add.add_argument(
        "--embed-key", action="store_true",
        help=t("sv.help.add_embed"),
    )

    sub.add_parser("list-clients", help=t("sv.help.list_clients"))

    p_revoke = sub.add_parser("revoke-client", help=t("sv.help.revoke"))
    p_revoke.add_argument("name", help=t("sv.help.revoke_name"))

    p_disable = sub.add_parser(
        "disable-client",
        help=t("sv.help.disable"),
    )
    p_disable.add_argument("name", help=t("sv.help.disable_name"))

    p_enable = sub.add_parser("enable-client", help=t("sv.help.enable"))
    p_enable.add_argument("name", help=t("sv.help.enable_name"))

    p_rotate = sub.add_parser(
        "rotate-client",
        help=t("sv.help.rotate"),
    )
    p_rotate.add_argument("name", help=t("sv.help.rotate_name"))

    p_prune = sub.add_parser(
        "prune-expired", help=t("sv.help.prune")
    )
    p_prune.add_argument(
        "--yes", "-y", action="store_true", help=t("sv.help.yes")
    )

    p_renew = sub.add_parser(
        "renew-cert",
        help=t("sv.help.renew"),
    )
    p_renew.add_argument(
        "--new-key", action="store_true",
        help=t("sv.help.renew_new_key"),
    )

    sub.add_parser("status", help=t("sv.help.status"))

    sub.add_parser(
        "restart",
        help=t("sv.help.restart"),
    )

    p_uninstall = sub.add_parser("uninstall", help=t("sv.help.uninstall"))
    p_uninstall.add_argument(
        "--yes", "-y", action="store_true", help=t("sv.help.yes")
    )

    sub.add_parser(
        "doctor",
        help=t("sv.help.doctor"),
    )

    sub.add_parser(
        "tui",
        help=t("sv.help.tui"),
    )

    sub.add_parser(
        "gui",
        help=t("sv.help.gui"),
    )

    p_web = sub.add_parser(
        "web",
        help=t("sv.help.web"),
    )
    p_web.add_argument(
        "--host", default="0.0.0.0",
        help=t("sv.help.web_host"),
    )
    p_web.add_argument(
        "--port", type=int, default=8443, help=t("sv.help.web_port")
    )
    p_web.add_argument(
        "--cert", default=None, help=t("sv.help.web_cert")
    )
    p_web.add_argument(
        "--key", default=None, help=t("sv.help.web_key")
    )

    p_token = sub.add_parser(
        "admin-token",
        help=t("sv.help.token"),
    )
    p_token.add_argument(
        "--rotate", action="store_true",
        help=t("sv.help.token_rotate"),
    )

    p_update = sub.add_parser(
        "update",
        help=t("sv.help.update"),
    )
    p_update.add_argument(
        "--check-only",
        action="store_true",
        help=t("sv.help.update_check"),
    )

    return parser


def _cmd_tui(args: argparse.Namespace) -> int:
    try:
        from outwarp_server.tui.app import OutWarpServerTUI
    except ImportError as exc:
        console.print(t("sv.tui.missing", error=exc))
        return 1
    config_dir = Path(args.config_dir) if args.config_dir else default_config_dir()
    return OutWarpServerTUI(config_dir).run() or 0


def _cmd_gui(args: argparse.Namespace) -> int:
    """Delegate to outwarp_server.server_app:main — the pywebview admin GUI.

    Was the dedicated ``outwarp-server-gui`` binary in 0.4.x; collapsed into a
    subcommand in 0.5.0 so the Linux install surface is a single executable.
    """
    from outwarp_server.server_app import main as _gui_main
    return _gui_main() or 0


def _config_dir_from_args(args: argparse.Namespace) -> Path:
    return Path(args.config_dir) if args.config_dir else default_config_dir()


def _cmd_admin_token(args: argparse.Namespace) -> int:
    """Print or rotate the web panel's admin token.

    Only the salted hash is stored, so an existing token can't be re-printed —
    rotating mints a fresh one and invalidates the old.
    """
    from outwarp_server.web_auth import generate_and_store_token, token_is_set

    config_dir = _config_dir_from_args(args)
    if token_is_set(config_dir) and not args.rotate:
        console.print(t("sv.token.exists"))
        return 0
    token = generate_and_store_token(config_dir)
    console.print(t("sv.token.generated") + "\n")
    console.print(f"  [bold]{token}[/bold]\n")
    console.print(t("sv.token.use"), style="dim")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    """Run the remote HTTPS admin panel.

    Serves the same UI the desktop GUI uses, but over the network behind a
    token login. Reuses the server's self-signed TLS cert; the browser will
    warn about the self-signed cert (or front it with an SSH tunnel).
    """
    import signal
    import threading

    from outwarp_server.logs import setup_logging
    from outwarp_server.server_manager import ServerManager
    from outwarp_server.web_auth import token_is_set

    config = _load_config(args)
    config_dir = _config_dir_from_args(args)

    if not token_is_set(config_dir):
        console.print(t("sv.web.no_token"))
        return 1

    certfile = args.cert or config.cert_path
    keyfile = args.key or config.key_path
    if not (Path(certfile).exists() and Path(keyfile).exists()):
        console.print(t("sv.web.no_cert", cert=certfile, key=keyfile))
        return 1

    memory_handler = setup_logging()
    manager = ServerManager(config, config_path=_resolve_config_path(args))

    from outwarp_server.api import Api
    from outwarp_server.logs import serve_log_path
    from outwarp_server.web_server import serve

    # In a container the tunnel runs in a separate `serve` process; its log
    # file on the shared config dir is what the Logs screen can show.
    api = Api(memory_handler, manager, extra_log_files=[serve_log_path(config_dir)])
    httpd = serve(
        api,
        ui_dir=Path(__file__).parent / "ui",
        config_dir=config_dir,
        host=args.host,
        port=args.port,
        certfile=certfile,
        keyfile=keyfile,
    )

    shown_host = "127.0.0.1" if args.host in ("127.0.0.1", "localhost") else config.endpoint
    console.print(t("sv.web.listening", url=f"https://{args.host}:{args.port}"))
    if args.host not in ("127.0.0.1", "localhost"):
        console.print(t("sv.web.exposed"))
    console.print(t("sv.web.open", url=f"https://{shown_host}:{args.port}"), style="dim")

    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    stop_event.wait()

    console.print(t("sv.web.shutdown"))
    with contextlib.suppress(Exception):
        httpd.shutdown()
    api.shutdown()
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Check GitHub Releases for a newer outwarp-server wheel and install it."""
    import tempfile

    from outwarp_server import updater as _upd

    console.print(t("sv.update.checking", version=__version__))
    info = _upd.check_for_update(__version__)

    if info.get("error"):
        console.print(t("sv.update.check_failed", error=info["error"]))
        return 1

    if not info.get("available"):
        latest = info.get("latest") or __version__
        # If a newer tag exists but the release has no Linux wheel attached
        # (e.g. an older Windows-only release), say so explicitly rather than
        # claiming we're already on the latest version.
        from outwarp_server.updater import _is_newer as _newer
        if latest and _newer(latest, __version__) and not info.get("wheel_url"):
            console.print(t("sv.update.no_wheel", latest=latest))
            console.print(t("sv.update.see", url=info.get("html_url", "")))
        else:
            console.print(t("sv.update.up_to_date", latest=latest))
        return 0

    latest = info["latest"]
    console.print(t("sv.update.available", latest=latest))
    console.print(t("sv.update.release", url=info.get("html_url", "")))

    if args.check_only:
        console.print(t("sv.update.run_hint"))
        return 0

    # Anything below this line writes to the venv (pip install --upgrade) or
    # the system temp dir as root. Enforce the root check here — not in the
    # dispatcher — so ``outwarp-server update --check-only`` above stays open
    # to unprivileged users.
    if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() != 0:
        console.print(t("sv.update.need_root"))
        return 1

    wheel_url = info.get("wheel_url", "")
    wheel_name = info.get("wheel_name") or Path(wheel_url).name
    if not wheel_url:
        console.print(t("sv.update.no_wheel_in", latest=latest, url=info.get("html_url", "")))
        return 1

    tmp_dir = Path(tempfile.mkdtemp())
    wheel_path = tmp_dir / wheel_name

    try:
        console.print(t("sv.update.downloading", name=wheel_name))
        last_milestone = [-1]

        def _progress(pct: int) -> None:
            milestone = pct // 20
            if milestone > last_milestone[0]:
                last_milestone[0] = milestone
                console.print(f"  {pct}%")

        try:
            _upd.download_wheel(wheel_url, wheel_path, _progress)
        except Exception as exc:
            console.print(t("sv.update.download_failed", error=exc))
            return 1

        ok, detail = _upd.verify_wheel(
            wheel_path, wheel_name,
            info.get("checksums_url", ""), info.get("signature_url", ""),
        )
        if not ok:
            console.print(t("sv.update.integrity_failed", detail=detail))
            return 1
        console.print(f"  {detail}")

        console.print(t("sv.update.installing"))
        try:
            _upd.apply_update(wheel_path, extras="tui")
        except subprocess.TimeoutExpired:
            console.print(t("sv.update.pip_timeout"))
            return 1
        except Exception as exc:
            console.print(t("sv.update.pip_failed", error=exc))
            return 1

        console.print("\n" + t("sv.update.updated", latest=latest))
        console.print(t("sv.update.restart"))
        return 0
    finally:
        with contextlib.suppress(OSError):
            wheel_path.unlink(missing_ok=True)
            tmp_dir.rmdir()


_COMMANDS: dict[str, callable] = {
    "setup": _cmd_setup,
    "init": _cmd_init,
    "serve": _cmd_serve,
    "enroll-listener": _cmd_enroll_listener,
    "add-client": _cmd_add_client,
    "list-clients": _cmd_list_clients,
    "revoke-client": _cmd_revoke_client,
    "rotate-client": _cmd_rotate_client,
    "disable-client": _cmd_disable_client,
    "enable-client": _cmd_enable_client,
    "renew-cert": _cmd_renew_cert,
    "prune-expired": _cmd_prune_expired,
    "status": _cmd_status,
    "restart": _cmd_restart,
    "uninstall": _cmd_uninstall,
    "doctor": _cmd_doctor,
    "tui": _cmd_tui,
    "gui": _cmd_gui,
    "web": _cmd_web,
    "admin-token": _cmd_admin_token,
    "update": _cmd_update,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args(argv)
    if getattr(args, "config_dir", None):
        os.environ[CONFIG_DIR_ENV] = str(Path(args.config_dir))
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    # Skip the root check only under the test harness. --config-dir does NOT
    # imply this: a container deployment passes it routinely to point at a
    # mounted /data (see README's `docker run -v outwarp-data:/data`), and
    # that must still be root inside the container — the flag says where the
    # privileged commands read/write, not who's allowed to run them.
    if args.command in _PRIVILEGED_COMMANDS and os.environ.get("OUTWARP_TEST_MODE") != "1":
        _require_root(args.command)
    return handler(args)
