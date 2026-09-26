"""Turn a saved server config into running OS services (native Linux install).

Shared by the CLI wizard (`outwarp-server setup`) and the desktop GUI's setup
so both leave the same system behind. The GUI used to save the config and
only start wstunnel as its own subprocess: closing the GUI stopped the tunnel,
nothing started it at boot and enrolment had no listener (B-031).
No rich/console output here; callers report each step their own way.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from outwarp_server.config import ServerConfig
from outwarp_server.platforms import PlatformError, get_server_platform
from outwarp_server.server_manager import build_enroll_listener_command, build_wstunnel_command
from outwarp_server.wireguard import build_platform_wg_conf

log = logging.getLogger(__name__)

SYSCTL_DROP_IN = Path("/etc/sysctl.d/99-outwarp.conf")

# (step, ok, detail). Steps: "forwarding", "wireguard", "ufw", "wstunnel", "enroll".
Report = Callable[[str, bool, str], None]


def enable_ip_forwarding() -> None:
    """Write a sysctl drop-in so ip_forward survives reboots (Linux only)."""
    if sys.platform != "linux":
        return
    try:
        SYSCTL_DROP_IN.write_text("net.ipv4.ip_forward = 1\n", encoding="utf-8")
        subprocess.run(["sysctl", "-p", str(SYSCTL_DROP_IN)], capture_output=True, check=False)
        log.info("IP forwarding enabled persistently via %s", SYSCTL_DROP_IN)
    except OSError as exc:
        log.warning(
            "Could not write %s: %s — IP forwarding must be enabled manually",
            SYSCTL_DROP_IN, exc,
        )


def configure_ufw_if_active(wss_port: int) -> bool:
    """If ufw is active, open the wstunnel port and allow forwarding. Returns
    whether ufw was active (and so touched)."""
    if sys.platform != "linux":
        return False
    try:
        result = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if "Status: active" not in result.stdout:
        return False

    subprocess.run(["ufw", "allow", f"{wss_port}/tcp"], capture_output=True, check=False)
    ufw_default = Path("/etc/default/ufw")
    if ufw_default.exists():
        try:
            content = ufw_default.read_text(encoding="utf-8")
            if 'DEFAULT_FORWARD_POLICY="DROP"' in content:
                ufw_default.write_text(
                    content.replace(
                        'DEFAULT_FORWARD_POLICY="DROP"', 'DEFAULT_FORWARD_POLICY="ACCEPT"',
                    ),
                    encoding="utf-8",
                )
                subprocess.run(["ufw", "reload"], capture_output=True, check=False)
        except OSError as exc:
            log.warning("Could not update ufw default forward policy: %s", exc)
    return True


def install_services(
    config: ServerConfig, config_path: Path, wstunnel_bin: Path, report: Report,
) -> bool:
    """Bring WireGuard up and install the wstunnel and enrolment units.

    Stops at the first failure (reported with ok=False) and returns False.
    The domain branch's Caddy front is not part of this: only the CLI wizard
    offers it.
    """
    enable_ip_forwarding()
    report("forwarding", True, "")

    platform = get_server_platform()
    try:
        # Re-running setup on a live interface: a hot reload would not re-run
        # PostUp, so force a full restart to guarantee the NAT rules.
        platform.reconcile(
            build_platform_wg_conf(config), subnet=config.subnet, wss_port=config.port,
            force_restart=platform.is_wg_active(),
        )
    except PlatformError as exc:
        report("wireguard", False, str(exc))
        return False
    report("wireguard", True, "")

    if configure_ufw_if_active(config.port):
        report("ufw", True, "")

    try:
        platform.install_wstunnel_service(" ".join(build_wstunnel_command(config, wstunnel_bin)))
    except PlatformError as exc:
        report("wstunnel", False, str(exc))
        return False
    report("wstunnel", True, "")

    # Without this, enrolment profiles are dead on a systemd install: nothing
    # else runs the token listener once setup exits.
    try:
        platform.install_enroll_service(" ".join(build_enroll_listener_command(config_path)))
    except PlatformError as exc:
        report("enroll", False, str(exc))
        return False
    report("enroll", True, "")
    return True
