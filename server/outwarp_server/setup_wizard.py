from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from outwarp_server.config import ServerConfig
from outwarp_server.crypto import generate_tls_cert, generate_upgrade_path, generate_wg_keypair
from outwarp_server.i18n import t
from outwarp_server.platforms import get_server_platform
from outwarp_server.platforms.base import PrerequisiteStatus
from outwarp_server.service_install import install_services

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
            t("wz.title"),
            border_style="cyan",
        )
    )

    if not _check_root():
        console.print(t("wz.need_root"))
        return 1

    config_path = config_dir / "server_config.json"
    if config_path.exists():
        console.print("\n" + t("wz.config_exists", path=config_path))
        if not Confirm.ask(t("wz.overwrite"), default=False):
            console.print(t("sv.aborted"))
            return 0

    # Check binaries
    console.print("\n" + t("wz.checking_deps"))
    wstunnel_bin = _find_wstunnel()
    if wstunnel_bin is None:
        console.print(t("wz.no_wstunnel"))
        return 1
    console.print(t("wz.found_wstunnel", path=wstunnel_bin))

    wg_bin = _find_wg()
    if wg_bin is None:
        console.print(t("wz.no_wg"))
        return 1
    console.print(t("wz.found_wg", path=wg_bin))

    # OS-level prereqs: NetNat WMI provider on Windows (no-op on Linux).
    # If we proceed without this, the server starts, wstunnel listens, but
    # client traffic gets no return path (NAT silently absent). Bail loudly.
    console.print("\n" + t("wz.checking_os"))
    prereq = get_server_platform().check_prerequisites()
    if prereq.status is PrerequisiteStatus.REBOOT_REQUIRED:
        console.print(f"  [yellow]⚠[/yellow]  {prereq.detail}")
        console.print(f"\n  [bold]{prereq.remediation}[/bold]")
        return 2
    if prereq.status is PrerequisiteStatus.FAILED:
        console.print(f"  [red]✗[/red] {prereq.detail}")
        console.print(f"\n{prereq.remediation}")
        return 1
    console.print(t("wz.nat_ok"))

    # Transport branch. This is the decision that determines whether the server
    # survives a network that inspects TLS, so it comes before anything else.
    console.print(
        Panel(
            t("wz.transport.body"),
            border_style="cyan",
            title=t("wz.transport.title"),
        )
    )
    if sys.platform == "linux":
        use_domain = Confirm.ask(t("wz.have_domain"), default=False)
    else:
        # Everything the Caddy front touches — /etc/caddy, systemd, the decoy
        # site — is POSIX-only. Offering the choice here would write a
        # configuration nothing on this host would ever read.
        console.print("\n" + t("wz.domain_linux_only"))
        use_domain = False
    tls_mode = "acme" if use_domain else "self-signed"

    if use_domain:
        endpoint = Prompt.ask(t("wz.domain_prompt"))
        while not endpoint.strip() or "/" in endpoint:
            console.print(t("wz.domain_invalid"))
            endpoint = Prompt.ask(t("wz.domain_prompt"))
        endpoint = endpoint.strip()
        acme_email = Prompt.ask(t("wz.acme_email"), default="").strip()
    else:
        console.print("\n" + t("wz.detecting_ip"))
        detected_ip = _detect_public_ip()
        if detected_ip:
            console.print(t("wz.detected", ip=detected_ip))
            endpoint = Prompt.ask(t("wz.endpoint_prompt"), default=detected_ip)
        else:
            console.print(t("wz.detect_failed"))
            endpoint = Prompt.ask(t("wz.endpoint_prompt"))
        acme_email = ""

    # Ports
    console.print("\n" + t("wz.network"))
    port_label = t("wz.port_caddy") if use_domain else t("wz.port_wstunnel")
    port = IntPrompt.ask(port_label, default=443)
    while not (1 <= port <= 65535):
        console.print(t("wz.invalid_port"))
        port = IntPrompt.ask(port_label, default=443)

    internal_ws_port = 8080
    if use_domain:
        internal_ws_port = IntPrompt.ask(t("wz.internal_port"), default=8080)

    wg_listen_port = IntPrompt.ask(t("wz.wg_port"), default=51820)

    # Subnet
    subnet = Prompt.ask(t("wz.subnet"), default="10.0.0.0/24")
    server_address = Prompt.ask(
        t("wz.server_address"), default=f"{subnet.split('/')[0].rsplit('.', 1)[0]}.1/24"
    )

    # Generate secrets
    console.print("\n" + t("wz.generating"))
    upgrade_path = generate_upgrade_path()
    console.print(t("wz.gen.path"))

    # Generated in both branches: the web admin panel serves HTTPS from this
    # certificate regardless of who holds the public port, and it is what a
    # later switch back to the self-signed branch would need.
    cert_dir = config_dir / "tls"
    cert_path, key_path, fingerprint, spki = generate_tls_cert(endpoint, cert_dir)
    if use_domain:
        console.print(t("wz.gen.cert_internal"))
    else:
        console.print(t("wz.gen.cert", fingerprint=fingerprint[:23]))

    wg_priv, wg_pub = generate_wg_keypair(wg_bin)
    console.print(t("wz.gen.keypair"))

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
    console.print(t("wz.config_saved", path=config_path))

    console.print("\n" + t("wz.installing"))
    labels = {
        "wireguard": (t("wz.svc.wg_done"), "WireGuard"),
        "ufw": (t("wz.svc.ufw_done"), "ufw"),
        "wstunnel": (t("wz.svc.wstunnel_done"), "wstunnel"),
        "enroll": (t("wz.svc.enroll_done"), t("wz.svc.enroll_name")),
    }

    def _report(step: str, ok: bool, detail: str) -> None:
        if step not in labels:
            return
        done, name = labels[step]
        if ok:
            console.print(f"  [green]✓[/green] {done}")
        else:
            console.print(f"  [red]✗[/red] {name}: {detail}")

    if not install_services(config, config_path, wstunnel_bin, _report):
        return 1

    if use_domain:
        _configure_caddy(config)

    # Connectivity probe (localhost only). In the domain branch wstunnel is on
    # loopback and Caddy owns the public port, so probe the one wstunnel holds.
    console.print("\n" + t("wz.probe"))
    probe_port = internal_ws_port if use_domain else port
    probe_ok = _probe_localhost(probe_port)
    if probe_ok:
        console.print(t("wz.probe_ok"))
    else:
        console.print(t("wz.probe_failed"))

    # Final summary
    transport = (
        t("wz.done.transport_caddy", port=port, internal=internal_ws_port)
        if use_domain
        else t("wz.done.transport_self", port=port)
    )
    dns_step = (
        t("wz.done.step_domain", endpoint=endpoint, port=port)
        if use_domain
        else t("wz.done.step_port", port=port)
    )
    console.print(
        Panel.fit(
            t("wz.done.body", endpoint=f"{endpoint}:{port}", transport=transport,
              wg=f"{server_address} (port {wg_listen_port})", subnet=subnet,
              dns_step=dns_step),
            border_style="green",
        )
    )
    return 0


def _configure_caddy(config: ServerConfig) -> None:
    """Write the Caddy front for the domain branch and reload it."""
    from outwarp_server import caddy

    console.print("\n" + t("wz.caddy.configuring"))
    if caddy.find_caddy() is None:
        console.print(t("wz.caddy.not_installed", hint=caddy.install_hint()))
    try:
        warnings = caddy.apply(
            config.endpoint,
            config.http_upgrade_path_prefix,
            internal_ws_port=config.internal_ws_port,
            acme_email=config.acme_email,
        )
    except caddy.CaddyError as exc:
        console.print(t("wz.caddy.failed", error=exc))
        return
    console.print(t("wz.caddy.decoy", path=caddy.DEFAULT_DECOY_DIR))
    console.print(t("wz.caddy.site", path=caddy.CADDY_SITE_FILE))
    for w in warnings:
        console.print(f"  [yellow]⚠[/yellow]  {w}")
    if not warnings:
        console.print(t("wz.caddy.reloaded"))


def _probe_localhost(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return True
    except (OSError, TimeoutError):
        return False
