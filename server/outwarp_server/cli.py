from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from rich.console import Console
from rich.table import Table

from outwarp_server import __version__
from outwarp_server.config import (
    ConfigError,
    ServerConfig,
    default_config_dir,
    default_config_path,
)
from outwarp_server.wireguard import (
    build_server_wg_conf,
    get_live_peers,
    remove_peer_live,
)

log = logging.getLogger(__name__)
console = Console()


# Commands that read/modify privileged state (systemd, /etc/wireguard, wg interface).
# Anything not in this set runs without a root check (--version, --help).
_PRIVILEGED_COMMANDS = frozenset({
    "setup", "add-client", "list-clients", "revoke-client", "prune-expired",
    "status", "restart", "uninstall", "doctor", "init", "serve", "tui",
})


def _require_root(command: str) -> None:
    """Exit with a friendly error if the current user can't run privileged ops."""
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                return
        except Exception:
            return
        console.print(
            "[red]Error:[/red] This command must be run as Administrator.\n"
            f"  Open an elevated PowerShell and run: [bold]outwarp-server {command}[/bold]"
        )
        raise SystemExit(1)

    if os.geteuid() == 0:
        return
    console.print(
        f"[red]Error:[/red] This command must be run as root.\n"
        f"  Try: [bold]sudo outwarp-server {command}[/bold]"
    )
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
        console.print(f"[red]Error:[/red] {exc}")
        console.print(
            "Run [bold]outwarp-server setup[/bold] first to configure the server."
        )
        raise SystemExit(1)


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


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the server in foreground — intended for Docker/Kubernetes.

    Loads server_config.json, starts wstunnel + WireGuard via ServerManager,
    and blocks until SIGTERM or SIGINT.
    """
    import signal
    import threading

    from outwarp_server.server_manager import ServerManager

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = _load_config(args)
    manager = ServerManager(config)
    manager.add_listener(lambda state: log.info("Server state: %s", state.value))
    manager.start()

    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    log.info("OutWarp server running. Send SIGTERM or Ctrl+C to stop.")
    stop_event.wait()

    log.info("Shutting down...")
    manager.stop()
    log.info("Done.")
    return 0


def _expiry_from_days(days: int | None) -> str:
    """Turn a --days count into an ISO expiry date, or '' for no expiry."""
    if not days:
        return ""
    import datetime

    if days < 1:
        raise ValueError("--days must be a positive number of days")
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

    try:
        result = operations.add_client(
            config,
            name,
            config_path=_resolve_config_path(args),
            expires_at=expires_at,
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    except Exception as exc:
        console.print(f"[red]Error generating WireGuard keys:[/red] {exc}")
        return 1

    console.print(f"\n[green]Client '{name}' added successfully.[/green]")
    console.print(f"  IP: {result.client.address}")
    if result.client.psk:
        console.print("  Preshared key: [green]yes[/green]")
    if expires_at:
        console.print(f"  Expires: [yellow]{expires_at}[/yellow]")
    console.print(f"  Config: [bold]{result.owcfg_path}[/bold]")
    console.print(
        "\nSend this .owcfg file to the client securely — "
        "it contains the client's private key."
    )
    return 0


def _cmd_prune_expired(args: argparse.Namespace) -> int:
    import datetime

    config = _load_config(args)
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    expired = [c for c in config.clients if c.expires_at and c.expires_at < today]

    if not expired:
        console.print("[green]No expired clients.[/green]")
        return 0

    console.print("[bold]Expired clients:[/bold]")
    for c in expired:
        console.print(f"  • {c.name} (expired {c.expires_at})")

    if not args.yes:
        answer = console.input("\nRevoke all of them? Type [bold]yes[/bold] to confirm: ")
        if answer.strip().lower() != "yes":
            console.print("Aborted.")
            return 1

    from outwarp_server.platforms import PlatformError, get_server_platform

    remaining = [c for c in config.clients if not (c.expires_at and c.expires_at < today)]
    for c in expired:
        try:
            remove_peer_live(c.public_key)
        except Exception as exc:
            log.warning("Could not hot-remove peer %s: %s", c.name, exc)

    updated = replace(config, clients=remaining)
    updated.save(_resolve_config_path(args))
    try:
        get_server_platform().install_wg_config(build_server_wg_conf(updated))
    except PlatformError as exc:
        log.warning("Could not persist WG config to OS location: %s", exc)

    console.print(f"\n[green]Revoked {len(expired)} expired client(s).[/green]")
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
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h ago"


# A peer is considered "online" if its last handshake is within this window.
# WireGuard renews handshakes roughly every 2 minutes; 3 minutes leaves margin.
_ONLINE_WINDOW_SECONDS = 180


def _cmd_list_clients(args: argparse.Namespace) -> int:
    import datetime
    import time

    config = _load_config(args)

    if not config.clients:
        console.print("No clients registered. Use [bold]add-client[/bold] to add one.")
        return 0

    live_peers = get_live_peers()
    now = int(time.time())

    today = datetime.datetime.now(datetime.UTC).date().isoformat()

    table = Table(title="Registered Clients")
    table.add_column("Name", style="bold")
    table.add_column("Address")
    table.add_column("Status")
    table.add_column("Last handshake")
    table.add_column("Endpoint")
    table.add_column("RX / TX")
    table.add_column("Expires")

    for c in config.clients:
        live = live_peers.get(c.public_key)
        if live is None:
            # Peer not even known to running WG (interface down, or peer not synced)
            status = "[dim]unknown[/dim]"
            handshake = "[dim]—[/dim]"
            endpoint = "[dim]—[/dim]"
            transfer = "[dim]—[/dim]"
        elif live.latest_handshake is None:
            status = "[yellow]idle[/yellow]"
            handshake = "[dim]never[/dim]"
            endpoint = "[dim]—[/dim]"
            transfer = "0 B / 0 B"
        else:
            seconds_ago = now - live.latest_handshake
            if seconds_ago < _ONLINE_WINDOW_SECONDS:
                status = "[green]online[/green]"
            else:
                status = "[yellow]offline[/yellow]"
            handshake = _format_seconds_ago(seconds_ago)
            endpoint = live.endpoint or "[dim]—[/dim]"
            transfer = f"{_format_bytes(live.transfer_rx)} / {_format_bytes(live.transfer_tx)}"

        if not c.expires_at:
            expires = "[dim]never[/dim]"
        elif c.expires_at < today:
            expires = f"[red]{c.expires_at} (expired)[/red]"
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
        console.print(f"[red]Error:[/red] {exc.args[0] if exc.args else exc}")
        return 1

    console.print(f"[green]Client '{name}' revoked.[/green]")
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    """Regenerate wg0.conf from current config and fully restart wg-quick + wstunnel.

    Use this after upgrading OutWarp or whenever PostUp/PostDown rules change —
    a hot reload (wg syncconf) does NOT re-run those scripts.
    """
    from outwarp_server import operations

    config = _load_config(args)

    console.print("[bold]Regenerating WireGuard config...[/bold]")
    result = operations.restart_services(config)

    if result.wg_conf_written:
        console.print("  [green]✓[/green] wg0.conf written")
    else:
        # The first error in restart_services always belongs to "WireGuard config".
        msg = result.errors[0] if result.errors else "WireGuard config write failed"
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print("[bold]Restarting WireGuard interface (PostUp/PostDown will re-run)...[/bold]")
    if result.wg_restarted:
        console.print("  [green]✓[/green] wg-quick restarted")
    else:
        msg = result.errors[0] if result.errors else "WireGuard restart failed"
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print("[bold]Restarting wstunnel service...[/bold]")
    if result.wstunnel_restarted:
        console.print("  [green]✓[/green] wstunnel restarted")
    else:
        msg = result.errors[-1] if result.errors else "wstunnel restart failed"
        console.print(f"  [red]✗[/red] {msg}")
        return 1

    console.print("\n[green]Server restarted successfully.[/green]")
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


def _cmd_uninstall(args: argparse.Namespace) -> int:
    from outwarp_server.platforms import PlatformError, get_server_platform

    config_path = _resolve_config_path(args)
    config_dir = config_path.parent
    platform = get_server_platform()
    install_prefix = platform.install_prefix()
    bin_link = platform.bin_link()

    console.print("[bold red]WARNING:[/bold red] This will permanently remove OutWarp server:")
    console.print("  • wstunnel systemd service")
    console.print("  • WireGuard interface, config and PostUp/PostDown rules")
    console.print(f"  • Server config and TLS certificates: {config_dir}")
    console.print("  • Persistent IP forwarding sysctl drop-in")
    if install_prefix is not None:
        console.print(f"  • Install directory: {install_prefix}")
    if bin_link is not None:
        console.print(f"  • CLI symlink: {bin_link}")

    if not args.yes:
        answer = console.input("\nType [bold]yes[/bold] to confirm: ")
        if answer.strip().lower() != "yes":
            console.print("Aborted.")
            return 1

    warnings: list[str] = []

    def _step(label: str, fn: callable) -> None:
        console.print(f"  {label}...", end=" ")
        try:
            fn()
            console.print("[green]done[/green]")
        except (PlatformError, OSError) as exc:
            console.print(f"[yellow]warning:[/yellow] {exc}")
            warnings.append(f"{label}: {exc}")

    console.print()
    _step("Stopping & removing wstunnel service", platform.uninstall_wstunnel_service)
    _step("Bringing down WireGuard + removing config", platform.uninstall_wg_config)

    def _rm_config_dir() -> None:
        import shutil
        if config_dir.exists():
            shutil.rmtree(config_dir)

    _step(f"Removing config dir ({config_dir})", _rm_config_dir)

    # Defer venv + symlink removal until after we exit (we live inside install_prefix).
    if install_prefix is not None and install_prefix.exists():
        try:
            _spawn_deferred_cleanup(install_prefix, bin_link)
            console.print(
                f"  Scheduled removal of {install_prefix}"
                + (f" and {bin_link}" if bin_link else "")
                + " after exit... [green]done[/green]"
            )
        except OSError as exc:
            console.print(f"  Scheduling cleanup... [yellow]warning:[/yellow] {exc}")
            warnings.append(f"deferred cleanup: {exc}")
    elif bin_link is not None and bin_link.exists():
        # No install prefix to remove (e.g., dev install) — just unlink the binary.
        _step(f"Removing CLI symlink ({bin_link})", lambda: bin_link.unlink())

    if warnings:
        console.print(
            "\n[yellow]Uninstall completed with warnings.[/yellow] "
            f"({len(warnings)} step(s) reported issues — see above.)"
        )
        return 1

    console.print("\n[green]OutWarp server uninstalled successfully.[/green]")
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

    table = Table(title="OutWarp Server Status", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Endpoint", f"{config.endpoint}:{config.port}")
    table.add_row("WireGuard subnet", config.subnet)
    table.add_row("Server WG address", config.server_address)
    table.add_row("WG listen port", str(config.wg_listen_port))
    table.add_row("Registered clients", str(len(config.clients)))

    def _status_cell(active: bool | None, error: str | None) -> str:
        if active is True:
            return "[green]running[/green]"
        if active is False:
            return "[red]stopped[/red]"
        return f"[yellow]unknown[/yellow] ({error})"

    table.add_row("wstunnel service", _status_cell(wstunnel_active, wstunnel_error))
    table.add_row("WireGuard interface", _status_cell(wg_active, wg_error))

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
            "[bold]Modo de pruebas / Doctor[/bold]\n"
            "Comprueba todo lo necesario para que el túnel funcione end-to-end.",
            border_style="cyan",
        )
    )

    results = run_all(config)

    table = Table(title="Resultados", show_lines=False)
    table.add_column("", width=2)
    table.add_column("Check", style="bold")
    table.add_column("Detalle")

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
        console.print("\n[bold]Acciones sugeridas:[/bold]")
        for r in needs_action:
            style = "red" if r.status == Status.FAIL else "yellow"
            console.print(f"  [{style}]•[/{style}] [bold]{r.name}[/bold]: {r.remediation}")

    summary = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 0, Status.SKIP: 0}
    for r in results:
        summary[r.status] += 1
    console.print(
        f"\n[green]{summary[Status.PASS]} OK[/green] / "
        f"[yellow]{summary[Status.WARN]} warn[/yellow] / "
        f"[red]{summary[Status.FAIL]} fail[/red]"
    )
    return 1 if summary[Status.FAIL] > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outwarp-server",
        description="OutWarp server — WireGuard over WebSocket tunnel manager",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Override the default config directory",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Run the interactive setup wizard")

    sub.add_parser(
        "init",
        help="Non-interactive init from env vars (Docker/Kubernetes) — "
             "generates config + TLS cert + WG keys without prompts",
    )

    sub.add_parser(
        "serve",
        help="Run the server in foreground (Docker/Kubernetes entrypoint) — "
             "starts wstunnel + WireGuard and blocks until SIGTERM",
    )

    p_add = sub.add_parser("add-client", help="Register a new client")
    p_add.add_argument("name", help="Client name (used as filename for .owcfg)")
    p_add.add_argument(
        "--days", type=int, default=None,
        help="Expire this client's config after N days (default: never)",
    )

    sub.add_parser("list-clients", help="List registered clients")

    p_revoke = sub.add_parser("revoke-client", help="Revoke a client")
    p_revoke.add_argument("name", help="Client name to revoke")

    p_prune = sub.add_parser(
        "prune-expired", help="Revoke every client whose --days expiry has passed"
    )
    p_prune.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )

    sub.add_parser("status", help="Show server status")

    sub.add_parser(
        "restart",
        help="Regenerate wg0.conf and fully restart wg-quick + wstunnel "
             "(use after upgrading or if PostUp rules changed)",
    )

    p_uninstall = sub.add_parser("uninstall", help="Remove OutWarp server completely")
    p_uninstall.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )

    sub.add_parser(
        "doctor",
        help="Run the full diagnostics battery (modo de pruebas) — "
             "checks NAT, forwarding, services, firewall, etc.",
    )

    sub.add_parser(
        "tui",
        help="Launch the interactive admin TUI (Linux / headless)",
    )

    return parser


def _cmd_tui(args: argparse.Namespace) -> int:
    try:
        from outwarp_server.tui.app import OutWarpServerTUI
    except ImportError as exc:
        console.print(
            "[red]TUI not installed.[/red] Reinstall with: "
            "[bold]pip install 'outwarp-server[tui]'[/bold]\n"
            f"  Underlying error: {exc}"
        )
        return 1
    config_dir = Path(args.config_dir) if args.config_dir else default_config_dir()
    return OutWarpServerTUI(config_dir).run() or 0


_COMMANDS: dict[str, callable] = {
    "setup": _cmd_setup,
    "init": _cmd_init,
    "serve": _cmd_serve,
    "add-client": _cmd_add_client,
    "list-clients": _cmd_list_clients,
    "revoke-client": _cmd_revoke_client,
    "prune-expired": _cmd_prune_expired,
    "status": _cmd_status,
    "restart": _cmd_restart,
    "uninstall": _cmd_uninstall,
    "doctor": _cmd_doctor,
    "tui": _cmd_tui,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    if args.command in _PRIVILEGED_COMMANDS:
        # Skip the root check when --config-dir points to a writable location
        # (used by tests). Real installations always use the default /etc path.
        if not args.config_dir:
            _require_root(args.command)
    return handler(args)
