from __future__ import annotations

import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from outwarp_server.config import ServerConfig
from outwarp_server.crypto import generate_tls_cert, generate_wg_keypair
from outwarp_server.platforms import PlatformError, get_server_platform
from outwarp_server.platforms.base import PrerequisiteStatus
from outwarp_server.server_manager import build_wstunnel_command
from outwarp_server.wireguard import build_server_wg_conf

log = logging.getLogger(__name__)
console = Console()

_PUBLIC_IP_SERVICE = "https://api.ipify.org"
_PUBLIC_IP_TIMEOUT = 5


def _detect_public_ip() -> str | None:
    try:
        with urllib.request.urlopen(_PUBLIC_IP_SERVICE, timeout=_PUBLIC_IP_TIMEOUT) as resp:
            return resp.read().decode("utf-8").strip()
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("Could not detect public IP: %s", exc)
        return None


def _check_root() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _find_wstunnel() -> Path | None:
    found = shutil.which("wstunnel")
    return Path(found) if found else None


def _find_wg() -> Path | None:
    found = shutil.which("wg")
    return Path(found) if found else None


def run_setup(config_dir: Path) -> int:
    """Interactive setup wizard. Returns exit code."""
    console.print(
        Panel.fit(
            "[bold cyan]OutWarp Server — Setup Wizard[/bold cyan]\n\n"
            "This wizard will configure wstunnel + WireGuard as system services.",
            border_style="cyan",
        )
    )

    if not _check_root():
        console.print(
            "[red]Error:[/red] This wizard must be run as root (or Administrator on Windows).\n"
            "  On Linux: [bold]sudo outwarp-server setup[/bold]"
        )
        return 1

    config_path = config_dir / "server_config.json"
    if config_path.exists():
        console.print(f"\n[yellow]Warning:[/yellow] Config already exists at {config_path}.")
        if not Confirm.ask("Overwrite existing configuration?", default=False):
            console.print("Aborted.")
            return 0

    # Check binaries
    console.print("\n[bold]Checking dependencies...[/bold]")
    wstunnel_bin = _find_wstunnel()
    if wstunnel_bin is None:
        console.print(
            "[red]Error:[/red] wstunnel binary not found in PATH.\n"
            "  Install from: https://github.com/erebe/wstunnel/releases"
        )
        return 1
    console.print(f"  [green]✓[/green] wstunnel: {wstunnel_bin}")

    wg_bin = _find_wg()
    if wg_bin is None:
        console.print(
            "[red]Error:[/red] WireGuard tools (wg) not found.\n"
            "  Install: [bold]apt install wireguard-tools[/bold] "
            "(Debian/Ubuntu) or equivalent."
        )
        return 1
    console.print(f"  [green]✓[/green] wg: {wg_bin}")

    # OS-level prereqs: NetNat WMI provider on Windows (no-op on Linux).
    # If we proceed without this, the server starts, wstunnel listens, but
    # client traffic gets no return path (NAT silently absent). Bail loudly.
    console.print("\n[bold]Checking OS prerequisites...[/bold]")
    prereq = get_server_platform().check_prerequisites()
    if prereq.status is PrerequisiteStatus.REBOOT_REQUIRED:
        console.print(f"  [yellow]⚠[/yellow]  {prereq.detail}")
        console.print(f"\n  [bold]{prereq.remediation}[/bold]")
        return 2
    if prereq.status is PrerequisiteStatus.FAILED:
        console.print(f"  [red]✗[/red] {prereq.detail}")
        console.print(f"\n{prereq.remediation}")
        return 1
    console.print("  [green]✓[/green] NAT prerequisites available")

    # Transport branch. This is the decision that determines whether the server
    # survives a network that inspects TLS, so it comes before anything else.
    console.print(
        Panel(
            "[bold]How should the server present itself on the public port?[/bold]\n\n"
            "[cyan]1. I have a domain[/cyan] (recommended)\n"
            "   Caddy holds port 443 with a real Let's Encrypt certificate and serves an\n"
            "   ordinary web page; the tunnel lives on a secret path behind it. Clients\n"
            "   validate the certificate normally. This is the only option that works on\n"
            "   networks that inspect TLS — corporate Wi-Fi, schools, hotel captive portals.\n\n"
            "[cyan]2. No domain[/cyan]\n"
            "   wstunnel holds the port with a self-signed certificate and clients pin it.\n"
            "   Nothing to buy or configure, and it is enough where the only obstacle is\n"
            "   blocked UDP — but the certificate is recognisably not a real one, so a\n"
            "   network that inspects TLS can single it out.",
            border_style="cyan",
            title="Transport",
        )
    )
    if sys.platform == "linux":
        use_domain = Confirm.ask(
            "Do you have a domain pointing at this server?", default=False
        )
    else:
        # Everything the Caddy front touches — /etc/caddy, systemd, the decoy
        # site — is POSIX-only. Offering the choice here would write a
        # configuration nothing on this host would ever read.
        console.print(
            "\n[yellow]The domain branch needs Caddy under systemd, so it is "
            "Linux-only for now.[/yellow] Continuing with the self-signed "
            "transport."
        )
        use_domain = False
    tls_mode = "acme" if use_domain else "self-signed"

    if use_domain:
        endpoint = Prompt.ask("Domain name (e.g. vpn.example.com)")
        while not endpoint.strip() or "/" in endpoint:
            console.print("[red]Enter a bare hostname, without scheme or path[/red]")
            endpoint = Prompt.ask("Domain name (e.g. vpn.example.com)")
        endpoint = endpoint.strip()
        acme_email = Prompt.ask(
            "Email for Let's Encrypt expiry notices (optional)", default=""
        ).strip()
    else:
        console.print("\n[bold]Detecting public IP...[/bold]")
        detected_ip = _detect_public_ip()
        if detected_ip:
            console.print(f"  Detected: [cyan]{detected_ip}[/cyan]")
            endpoint = Prompt.ask("Server endpoint (IP or domain)", default=detected_ip)
        else:
            console.print("  [yellow]Could not auto-detect[/yellow]")
            endpoint = Prompt.ask("Server endpoint (IP or domain)")
        acme_email = ""

    # Ports
    console.print("\n[bold]Network configuration[/bold]")
    port_label = "Public HTTPS port (Caddy)" if use_domain else "wstunnel WSS port"
    port = IntPrompt.ask(port_label, default=443)
    while not (1 <= port <= 65535):
        console.print("[red]Invalid port[/red]")
        port = IntPrompt.ask(port_label, default=443)

    internal_ws_port = 8080
    if use_domain:
        internal_ws_port = IntPrompt.ask(
            "Loopback port for wstunnel behind Caddy", default=8080
        )

    wg_listen_port = IntPrompt.ask("WireGuard listen port (loopback only)", default=51820)

    # Subnet
    subnet = Prompt.ask("WireGuard subnet (CIDR)", default="10.0.0.0/24")
    server_address = Prompt.ask(
        "Server's WireGuard address", default=f"{subnet.split('/')[0].rsplit('.', 1)[0]}.1/24"
    )

    # Generate secrets
    console.print("\n[bold]Generating cryptographic material...[/bold]")
    upgrade_path = secrets.token_urlsafe(32)
    console.print("  [green]✓[/green] HTTP upgrade path prefix")

    # Generated in both branches: the web admin panel serves HTTPS from this
    # certificate regardless of who holds the public port, and it is what a
    # later switch back to the self-signed branch would need.
    cert_dir = config_dir / "tls"
    cert_path, key_path, fingerprint, spki = generate_tls_cert(endpoint, cert_dir)
    if use_domain:
        console.print("  [green]✓[/green] TLS cert (internal use — Caddy serves the public one)")
    else:
        console.print(f"  [green]✓[/green] TLS cert ({fingerprint[:23]}...)")

    wg_priv, wg_pub = generate_wg_keypair(wg_bin)
    console.print("  [green]✓[/green] WireGuard server keypair")

    # Build and save server config
    config = ServerConfig(
        schema_version=1,
        endpoint=endpoint,
        port=port,
        http_upgrade_path_prefix=upgrade_path,
        cert_path=str(cert_path),
        key_path=str(key_path),
        cert_fingerprint_sha256=fingerprint,
        spki_sha256=spki,
        tls_mode=tls_mode,
        internal_ws_port=internal_ws_port,
        acme_email=acme_email,
        wg_private_key=wg_priv,
        wg_public_key=wg_pub,
        subnet=subnet,
        server_address=server_address,
        wg_listen_port=wg_listen_port,
        clients=[],
    )
    config.save(config_path)
    console.print(f"  [green]✓[/green] Server config saved to {config_path}")

    # Enable IP forwarding persistently (survives reboots).
    # PostUp in wg0.conf handles the runtime activation; this covers the
    # window between boot and wg-quick bringing the interface up.
    _enable_ip_forwarding(config_dir)

    # Install services via platform
    platform = get_server_platform()
    console.print("\n[bold]Installing services...[/bold]")

    try:
        wg_conf = build_server_wg_conf(config)
        # If the interface was already up (re-running setup), install_wg_config does
        # a hot reload via wg syncconf which doesn't re-run PostUp. Force a full
        # restart so the iptables/forwarding rules are guaranteed to be applied.
        was_active = platform.is_wg_active()
        platform.install_wg_config(wg_conf)
        if was_active:
            platform.restart_wg()
        console.print("  [green]✓[/green] WireGuard interface up")
    except PlatformError as exc:
        console.print(f"  [red]✗[/red] WireGuard: {exc}")
        return 1

    # ufw blocks FORWARD by default; allow the wstunnel port and enable forwarding.
    _configure_ufw_if_active(port)

    try:
        platform.install_wstunnel_service(
            " ".join(build_wstunnel_command(config, wstunnel_bin))
        )
        console.print("  [green]✓[/green] wstunnel service enabled")
    except PlatformError as exc:
        console.print(f"  [red]✗[/red] wstunnel: {exc}")
        return 1

    if use_domain:
        _configure_caddy(config)

    # Connectivity probe (localhost only). In the domain branch wstunnel is on
    # loopback and Caddy owns the public port, so probe the one wstunnel holds.
    console.print("\n[bold]Running connectivity probe...[/bold]")
    probe_port = internal_ws_port if use_domain else port
    probe_ok = _probe_localhost(probe_port)
    if probe_ok:
        console.print("  [green]✓[/green] wstunnel is listening on the configured port")
    else:
        console.print(
            "  [yellow]⚠[/yellow]  Could not connect locally — check service logs:\n"
            "     journalctl -u wstunnel-outwarp -e"
        )

    # Final summary
    transport = (
        f"Transport: [cyan]Caddy on {port} → wstunnel on 127.0.0.1:{internal_ws_port}[/cyan]\n"
        if use_domain
        else f"Transport: [cyan]wstunnel on {port} (self-signed, pinned)[/cyan]\n"
    )
    dns_step = (
        f"  1. Point {endpoint} at this server's public IP and make sure "
        f"port {port}/tcp is reachable — Caddy needs it to obtain the certificate.\n"
        if use_domain
        else f"  1. Make sure port {port}/tcp is open in your firewall and router.\n"
    )
    console.print(
        Panel.fit(
            f"[bold green]Setup complete![/bold green]\n\n"
            f"Endpoint:  [cyan]{endpoint}:{port}[/cyan]\n"
            f"{transport}"
            f"WireGuard: [cyan]{server_address} (port {wg_listen_port})[/cyan]\n"
            f"Subnet:    [cyan]{subnet}[/cyan]\n\n"
            f"[bold]Next steps:[/bold]\n"
            f"{dns_step}"
            f"  2. Run [bold]outwarp-server add-client <name>[/bold] to register clients.\n"
            f"  3. Send the generated .owcfg files to each client.",
            border_style="green",
        )
    )
    return 0


def _configure_caddy(config: ServerConfig) -> None:
    """Write the Caddy front for the domain branch and reload it."""
    from outwarp_server import caddy

    console.print("\n[bold]Configuring the Caddy front...[/bold]")
    if caddy.find_caddy() is None:
        console.print(
            "  [yellow]⚠[/yellow]  caddy is not installed. Writing the configuration "
            "anyway; install Caddy and reload it to finish:\n"
            f"     {caddy.install_hint()}"
        )
    try:
        warnings = caddy.apply(
            config.endpoint,
            config.http_upgrade_path_prefix,
            internal_ws_port=config.internal_ws_port,
            acme_email=config.acme_email,
            enroll_port=config.enroll_port,
        )
    except caddy.CaddyError as exc:
        console.print(f"  [red]✗[/red] Caddy: {exc}")
        return
    console.print(f"  [green]✓[/green] Decoy site at {caddy.DEFAULT_DECOY_DIR}")
    console.print(f"  [green]✓[/green] Site config at {caddy.CADDY_SITE_FILE}")
    for w in warnings:
        console.print(f"  [yellow]⚠[/yellow]  {w}")
    if not warnings:
        console.print("  [green]✓[/green] Caddy reloaded")


def _configure_ufw_if_active(wss_port: int) -> None:
    """If ufw is active, open the wstunnel port and allow IP forwarding."""
    if sys.platform != "linux":
        return
    try:
        result = subprocess.run(
            ["ufw", "status"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return
    if "Status: active" not in result.stdout:
        return

    console.print("  [yellow]ufw detected[/yellow] — opening port and enabling forwarding...")
    subprocess.run(["ufw", "allow", f"{wss_port}/tcp"], capture_output=True, check=False)

    ufw_default = Path("/etc/default/ufw")
    if ufw_default.exists():
        try:
            content = ufw_default.read_text(encoding="utf-8")
            if 'DEFAULT_FORWARD_POLICY="DROP"' in content:
                ufw_default.write_text(
                    content.replace(
                        'DEFAULT_FORWARD_POLICY="DROP"',
                        'DEFAULT_FORWARD_POLICY="ACCEPT"',
                    ),
                    encoding="utf-8",
                )
                subprocess.run(["ufw", "reload"], capture_output=True, check=False)
        except OSError as exc:
            log.warning("Could not update ufw default forward policy: %s", exc)

    console.print("  [green]✓[/green] ufw configured")


def _enable_ip_forwarding(config_dir: Path) -> None:
    """Write a sysctl drop-in so ip_forward survives reboots (Linux only)."""
    if sys.platform != "linux":
        return
    sysctl_path = Path("/etc/sysctl.d/99-outwarp.conf")
    try:
        sysctl_path.write_text("net.ipv4.ip_forward = 1\n", encoding="utf-8")
        import subprocess as _sp
        _sp.run(["sysctl", "-p", str(sysctl_path)], capture_output=True, check=False)
        log.info("IP forwarding enabled persistently via %s", sysctl_path)
    except OSError as exc:
        log.warning(
            "Could not write %s: %s — IP forwarding must be enabled manually", sysctl_path, exc,
        )


def _probe_localhost(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return True
    except (OSError, TimeoutError):
        return False
