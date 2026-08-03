from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from outwarp_server.config import ServerConfig

log = logging.getLogger(__name__)


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


# "auto"        → the UI can run fix_callable() after a confirmation prompt.
# "interactive" → requires a privileged shell session (apt install …); the UI
#                 surfaces the command for copy/paste instead of running it.
# "manual"      → informational. Showing the command for reference only.
FixKind = Literal["auto", "interactive", "manual"]


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    remediation: str | None = None
    # Bare command intended for the UI's "Copy" button — without surrounding
    # prose like "As admin: ...". Falls back to `remediation` when unset.
    remediation_command: str | None = None
    fix_kind: FixKind | None = None
    # Callable invoked by the TUI when fix_kind == "auto" and the user confirms.
    # Receives the ServerConfig the check ran against. Should raise on failure.
    fix_callable: Callable[[ServerConfig], None] | None = field(default=None, repr=False)


@dataclass
class Check:
    key: str
    category: str
    runner: Callable[[ServerConfig], CheckResult]


_WIN_WG_INTERFACE = "OutWarp-Server"
_WIN_NAT_NAME = "OutWarp"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ps(*args: str, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=_NO_WINDOW,
    )


def _sc(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sc", *args],
        capture_output=True,
        text=True,
        check=False,
        creationflags=_NO_WINDOW,
    )


# ───────── common (platform-agnostic) ─────────

def check_config_loadable(config: ServerConfig) -> CheckResult:
    return CheckResult(
        name="Server config loadable",
        status=Status.PASS,
        detail=f"endpoint={config.endpoint}:{config.port}, subnet={config.subnet}",
    )


def check_clients_registered(config: ServerConfig) -> CheckResult:
    if not config.clients:
        return CheckResult(
            name="Clients registered",
            status=Status.WARN,
            detail="No clients registered yet.",
            remediation="Run `outwarp-server add-client <name>` to issue a profile.",
            remediation_command="outwarp-server add-client <name>",
        )
    return CheckResult(
        name="Clients registered",
        status=Status.PASS,
        detail=f"{len(config.clients)} client(s)",
    )


def check_tls_cert_files(config: ServerConfig) -> CheckResult:
    # Use the paths stored in the config — these are the ones wstunnel actually
    # reads. The fallback to default_config_dir was wrong: the wizard may store
    # them anywhere, and the doctor would falsely flag them as missing.
    from pathlib import Path
    cert = Path(config.cert_path)
    key = Path(config.key_path)
    missing = [p for p in (cert, key) if not p.exists()]
    if missing:
        return CheckResult(
            name="TLS cert + key present",
            status=Status.FAIL,
            detail=f"Missing: {', '.join(str(p) for p in missing)}",
            remediation="Re-run `outwarp-server setup` to regenerate the TLS material.",
            remediation_command="outwarp-server setup",
        )
    return CheckResult(
        name="TLS cert + key present",
        status=Status.PASS,
        detail=str(cert.parent),
    )


def check_caddy_front(config: ServerConfig) -> CheckResult:
    """In the domain branch, Caddy is the thing holding the public port."""
    from outwarp_server import caddy

    name = "Caddy front"
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail="server is in self-signed mode"
        )

    if caddy.find_caddy() is None:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail="caddy is not installed, so nothing is terminating TLS on the public port",
            remediation=f"Install Caddy: {caddy.install_hint()}",
            remediation_command=caddy.install_hint(),
            fix_kind="interactive",
        )
    if not caddy.CADDY_SITE_FILE.exists():
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=f"{caddy.CADDY_SITE_FILE} is missing",
            remediation="Re-run `outwarp-server setup` to regenerate the Caddy front.",
            remediation_command="outwarp-server setup",
        )
    ok, detail = caddy.validate()
    if not ok:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=f"`caddy validate` rejected the configuration: {detail}",
            remediation="Fix the reported error, then: systemctl reload caddy",
            remediation_command="systemctl reload caddy",
        )
    return CheckResult(name=name, status=Status.PASS, detail=str(caddy.CADDY_SITE_FILE))


def check_public_certificate(config: ServerConfig) -> CheckResult:
    """Does the endpoint actually serve a certificate the world will trust?

    This is the check that tells the admin whether the domain branch delivered
    what it promises. Clients issued a CA-mode profile validate the chain the
    same way, so a failure here is a failure for every one of them.
    """
    import ssl

    name = "Public certificate trusted"
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail="self-signed mode pins instead"
        )
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((config.endpoint, config.port), timeout=6) as sock:
            ctx.wrap_socket(sock, server_hostname=config.endpoint).close()
    except ssl.SSLCertVerificationError as exc:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=f"{config.endpoint}:{config.port} — {exc.verify_message or exc}",
            remediation=(
                "Caddy could not obtain a certificate. Check that the domain's DNS "
                f"points here and that port {config.port}/tcp is reachable from the "
                "internet, then: journalctl -u caddy -e"
            ),
            remediation_command="journalctl -u caddy -e",
        )
    except OSError as exc:
        return CheckResult(
            name=name,
            status=Status.WARN,
            detail=f"Could not reach {config.endpoint}:{config.port} — {exc}",
            remediation=(
                "The certificate could not be checked because the endpoint was "
                "unreachable from the server itself; this is often just hairpin NAT."
            ),
        )
    return CheckResult(
        name=name, status=Status.PASS, detail=f"{config.endpoint}:{config.port}"
    )


def check_egress(config: ServerConfig) -> CheckResult:
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            pass
    except OSError as exc:
        return CheckResult(
            name="Outbound internet (TCP/443)",
            status=Status.FAIL,
            detail=f"Cannot reach 1.1.1.1:443 — {exc}",
            remediation="The server itself can't reach the internet — fix that first.",
        )
    return CheckResult(
        name="Outbound internet (TCP/443)",
        status=Status.PASS,
        detail="1.1.1.1:443 reachable in <3 s",
    )


# ───────── Windows ─────────

def check_win_admin(config: ServerConfig) -> CheckResult:
    import ctypes
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False
    if not is_admin:
        return CheckResult(
            name="Running as Administrator",
            status=Status.FAIL,
            detail="Many checks need an elevated shell to read real state.",
            remediation="Open an elevated PowerShell and re-run `outwarp-server doctor`.",
        )
    return CheckResult(name="Running as Administrator", status=Status.PASS)


def check_win_ip_forwarding(config: ServerConfig) -> CheckResult:
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "IPEnableRouter")
    except OSError as exc:
        return CheckResult(
            name="IP forwarding (IPEnableRouter)",
            status=Status.FAIL,
            detail=f"Cannot read registry: {exc}",
        )
    if int(value) == 1:
        return CheckResult(
            name="IP forwarding (IPEnableRouter)",
            status=Status.PASS,
            detail="IPEnableRouter = 1",
        )
    return CheckResult(
        name="IP forwarding (IPEnableRouter)",
        status=Status.FAIL,
        detail=f"IPEnableRouter = {value}",
        remediation=(
            "As admin: `Set-ItemProperty -Path "
            "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' "
            "-Name IPEnableRouter -Value 1` and reboot."
        ),
        remediation_command=(
            "Set-ItemProperty -Path "
            "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' "
            "-Name IPEnableRouter -Value 1"
        ),
    )


def check_win_forwarding_on_wg_iface(config: ServerConfig) -> CheckResult:
    result = _ps(
        f"Get-NetIPInterface -InterfaceAlias '{_WIN_WG_INTERFACE}' -AddressFamily IPv4 "
        f"-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Forwarding"
    )
    stdout = result.stdout.strip()
    if not stdout:
        return CheckResult(
            name=f"Forwarding on '{_WIN_WG_INTERFACE}'",
            status=Status.FAIL,
            detail="Interface not present.",
            remediation="WireGuard interface isn't installed. Run `outwarp-server restart`.",
            remediation_command="outwarp-server restart",
        )
    if "Enabled" in stdout:
        return CheckResult(
            name=f"Forwarding on '{_WIN_WG_INTERFACE}'",
            status=Status.PASS,
            detail="Enabled",
        )
    return CheckResult(
        name=f"Forwarding on '{_WIN_WG_INTERFACE}'",
        status=Status.FAIL,
        detail=stdout,
        remediation=(
            f"As admin: `Set-NetIPInterface -InterfaceAlias '{_WIN_WG_INTERFACE}' "
            f"-Forwarding Enabled`."
        ),
        remediation_command=(
            f"Set-NetIPInterface -InterfaceAlias '{_WIN_WG_INTERFACE}' -Forwarding Enabled"
        ),
    )


def check_win_netnat_provider(config: ServerConfig) -> CheckResult:
    """Probe whether the NetNat WMI class is registered.

    If not, every NAT cmdlet (New-NetNat, Get-NetNat, …) returns "Invalid class"
    / "Clase no válida" regardless of admin rights. The root cause is that the
    Windows Containers / Hyper-V feature isn't enabled — that feature ships the
    NAT driver and its WMI provider. This check is what unlocks the chain: when
    it fails, downstream NAT checks are noise.
    """
    result = _ps(
        "Get-CimClass -ClassName MSFT_NetNat -Namespace ROOT/StandardCimv2 "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty CimClassName"
    )
    if "MSFT_NetNat" in result.stdout:
        return CheckResult(name="NetNat provider (WMI class)", status=Status.PASS)
    return CheckResult(
        name="NetNat provider (WMI class)",
        status=Status.FAIL,
        detail=(
            "MSFT_NetNat is not registered — NAT cmdlets will fail with "
            "'Invalid class' / 'Clase no válida'."
        ),
        remediation=(
            "The Windows NAT infrastructure is not installed. Enable the "
            "'Containers' feature and reboot. On Windows Home (where Containers "
            "may be unavailable) enable Hyper-V instead — note Home only "
            "supports Hyper-V with unofficial workarounds."
        ),
        remediation_command=(
            "Enable-WindowsOptionalFeature -Online -FeatureName Containers -All"
        ),
    )


def check_win_netnat(config: ServerConfig) -> CheckResult:
    result = _ps(
        "Get-NetNat | Select-Object Name, InternalIPInterfaceAddressPrefix, Active "
        "| ConvertTo-Json -Compress"
    )
    raw = result.stdout.strip()
    err = (result.stderr or "").lower()
    # "Invalid class" (en) / "Clase no válida" (es) — the WMI provider is
    # missing entirely; surface that as the headline so the user doesn't chase
    # the wrong fix. The dedicated check_win_netnat_provider should already have
    # caught it, but this is the safety net for older deployments.
    if "invalid class" in err or "clase no v" in err:
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.FAIL,
            detail="Cannot query NetNat — WMI provider not registered.",
            remediation=(
                "Enable the 'Containers' Windows feature and reboot — that "
                "installs the NetNat WMI provider."
            ),
            remediation_command=(
                "Enable-WindowsOptionalFeature -Online -FeatureName Containers -All"
            ),
        )
    if not raw:
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.FAIL,
            detail="No NetNat instances exist at all.",
            remediation=(
                f"As admin: `New-NetNat -Name '{_WIN_NAT_NAME}' "
                f"-InternalIPInterfaceAddressPrefix '{config.subnet}'`. "
                "If this fails with 'Invalid class', the NAT provider is "
                "missing — enable the Containers Windows feature and reboot."
            ),
            remediation_command=(
                f"New-NetNat -Name '{_WIN_NAT_NAME}' "
                f"-InternalIPInterfaceAddressPrefix '{config.subnet}'"
            ),
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.WARN,
            detail=f"Unparseable Get-NetNat output: {raw[:200]}",
        )
    nats = data if isinstance(data, list) else [data]
    matching = [n for n in nats if n.get("InternalIPInterfaceAddressPrefix") == config.subnet]
    others = [n for n in nats if n.get("InternalIPInterfaceAddressPrefix") != config.subnet]

    if not matching:
        # Windows only honours ONE NetNat at a time — if another one (Hyper-V,
        # WSL2, Docker, Mobile Hotspot, ICS) was created first, ours is silently
        # ignored. This is the single most common cause of "ports open but no
        # return traffic" on Windows servers.
        listing = ", ".join(
            f"{n.get('Name')}({n.get('InternalIPInterfaceAddressPrefix')})" for n in nats
        )
        conflict_name = nats[0].get("Name") if nats else "<name>"
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.FAIL,
            detail=f"No NetNat covers {config.subnet}. Existing: {listing}",
            remediation=(
                "Windows allows only ONE active NetNat. Remove the conflicting one — "
                "e.g. `Remove-NetNat -Name <name> -Confirm:$false` (typical culprits: "
                "'WSL', 'Hyper-V', 'ICS', a Mobile Hotspot rule) — then run "
                "`outwarp-server restart`."
            ),
            remediation_command=(
                f"Remove-NetNat -Name '{conflict_name}' -Confirm:$false; "
                f"New-NetNat -Name '{_WIN_NAT_NAME}' "
                f"-InternalIPInterfaceAddressPrefix '{config.subnet}'"
            ),
        )

    found = matching[0]
    active = found.get("Active")
    if active is False or str(active).lower() == "false":
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.FAIL,
            detail=f"NAT '{found.get('Name')}' exists but Active=False.",
            remediation="Restart the WinNAT service: `Restart-Service WinNat`.",
            remediation_command="Restart-Service WinNat",
        )
    if others:
        listing = ", ".join(
            f"{n.get('Name')}({n.get('InternalIPInterfaceAddressPrefix')})" for n in others
        )
        return CheckResult(
            name="WinNAT rule for WG subnet",
            status=Status.WARN,
            detail=(
                f"OK for {config.subnet}, but additional NetNats exist: {listing}. "
                "Windows ignores all but one — return traffic may break unpredictably."
            ),
            remediation="Remove the extra NetNats unless you genuinely need them.",
        )
    return CheckResult(
        name="WinNAT rule for WG subnet",
        status=Status.PASS,
        detail=f"{found.get('Name')} → {config.subnet} (Active)",
    )


def check_win_winnat_service(config: ServerConfig) -> CheckResult:
    out = _sc("query", "WinNat").stdout
    if "RUNNING" in out:
        return CheckResult(name="WinNat service", status=Status.PASS, detail="RUNNING")
    if "STOPPED" in out:
        # NetNat creation triggers WinNat on demand, but only if startup is not
        # disabled. If `Start-Service` fails here, the underlying driver is
        # missing — almost always because Hyper-V / Containers features aren't
        # enabled. Suggest both the easy path and the diagnostic.
        return CheckResult(
            name="WinNat service",
            status=Status.FAIL,
            detail="Stopped — NetNat rules will NOT translate traffic.",
            remediation=(
                "As admin: `Set-Service WinNat -StartupType Automatic; Start-Service WinNat`. "
                "If start fails with 'service did not respond', the underlying NAT driver "
                "is missing — enable the 'Containers' or 'Hyper-V' Windows feature: "
                "`Enable-WindowsOptionalFeature -Online -FeatureName Containers -All` and reboot."
            ),
            remediation_command=(
                "Set-Service WinNat -StartupType Automatic; Start-Service WinNat"
            ),
        )
    if "FAILED" in out or not out.strip():
        # `sc query` returns "[SC] EnumQueryServicesStatus:OpenService FAILED 1060"
        # when the service literally doesn't exist on the machine.
        return CheckResult(
            name="WinNat service",
            status=Status.FAIL,
            detail="WinNat service not registered on this Windows install.",
            remediation=(
                "The NAT driver isn't installed. Enable the 'Containers' Windows feature: "
                "`Enable-WindowsOptionalFeature -Online -FeatureName Containers -All` and reboot."
            ),
            remediation_command=(
                "Enable-WindowsOptionalFeature -Online -FeatureName Containers -All"
            ),
        )
    return CheckResult(
        name="WinNat service",
        status=Status.WARN,
        detail=f"Unknown state: {out.strip()[:200]}",
    )


def check_win_wg_service(config: ServerConfig) -> CheckResult:
    out = _sc("query", f"WireGuardTunnel${_WIN_WG_INTERFACE}").stdout
    if "RUNNING" in out:
        return CheckResult(
            name="WireGuard tunnel service",
            status=Status.PASS,
            detail=f"WireGuardTunnel${_WIN_WG_INTERFACE}: RUNNING",
        )
    return CheckResult(
        name="WireGuard tunnel service",
        status=Status.FAIL,
        detail=f"Not running: {out.strip()[:200]}",
        remediation="As admin: `outwarp-server restart`.",
        remediation_command="outwarp-server restart",
    )


def check_win_wstunnel_running(config: ServerConfig) -> CheckResult:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq wstunnel.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=_NO_WINDOW,
    )
    if "wstunnel" in result.stdout.lower():
        return CheckResult(name="wstunnel process", status=Status.PASS, detail="running")
    return CheckResult(
        name="wstunnel process",
        status=Status.FAIL,
        detail="No wstunnel.exe found.",
        remediation="Start the OutWarp server (GUI or service) so it spawns wstunnel.",
    )


def check_win_listening_port(config: ServerConfig) -> CheckResult:
    result = _ps(
        f"Get-NetTCPConnection -State Listen -LocalPort {config.port} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess"
    )
    pid_str = result.stdout.strip()
    if not pid_str:
        return CheckResult(
            name=f"Listening on TCP/{config.port}",
            status=Status.FAIL,
            detail="No process bound to the WSS port.",
            remediation="Check the server logs — wstunnel probably failed to start.",
        )
    return CheckResult(
        name=f"Listening on TCP/{config.port}",
        status=Status.PASS,
        detail=f"PID {pid_str}",
    )


def check_win_firewall(config: ServerConfig) -> CheckResult:
    result = _ps(
        "Get-NetFirewallRule -DisplayName 'OutWarp-wstunnel' -ErrorAction SilentlyContinue "
        "| Select-Object Enabled, Action | ConvertTo-Json -Compress"
    )
    raw = result.stdout.strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return CheckResult(
                name="Firewall inbound rule",
                status=Status.WARN,
                detail=f"Unparseable: {raw[:200]}",
            )
        entries = data if isinstance(data, list) else [data]
        enabled_values = {str(e.get("Enabled")).lower() for e in entries}
        if "true" in enabled_values or "1" in enabled_values:
            return CheckResult(
                name="Firewall inbound rule",
                status=Status.PASS,
                detail="OutWarp-wstunnel enabled",
            )
        return CheckResult(
            name="Firewall inbound rule",
            status=Status.FAIL,
            detail=f"Rule exists but disabled: {raw}",
            remediation="As admin: `Enable-NetFirewallRule -DisplayName 'OutWarp-wstunnel'`.",
            remediation_command="Enable-NetFirewallRule -DisplayName 'OutWarp-wstunnel'",
        )
    # Legacy fallback for rules created via netsh.
    legacy = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", "name=OutWarp-wstunnel"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=_NO_WINDOW,
    )
    if "OutWarp-wstunnel" in legacy.stdout:
        return CheckResult(
            name="Firewall inbound rule",
            status=Status.PASS,
            detail="OutWarp-wstunnel rule present (netsh).",
        )
    return CheckResult(
        name="Firewall inbound rule",
        status=Status.WARN,
        detail="No 'OutWarp-wstunnel' rule found.",
        remediation=(
            f"As admin: `netsh advfirewall firewall add rule "
            f"name=OutWarp-wstunnel dir=in action=allow localport={config.port} protocol=TCP`."
        ),
        remediation_command=(
            f"netsh advfirewall firewall add rule name=OutWarp-wstunnel "
            f"dir=in action=allow localport={config.port} protocol=TCP"
        ),
    )


# ───────── Linux ─────────

_LINUX_WG_INTERFACE = "wg0"
_LINUX_SYSCTL_DROP_IN = "/etc/sysctl.d/99-outwarp.conf"


def _run_linux(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout,
    )


def _wg_tools_install_cmd() -> str:
    """Best-effort install command for wireguard-tools on the host's distro.

    The hardcoded `apt install` only made sense on Debian/Ubuntu; detect the
    available package manager so the remediation is copy-pasteable on Arch,
    Fedora, openSUSE and Alpine too.
    """
    if shutil.which("apt"):
        return "apt install wireguard-tools"
    if shutil.which("dnf"):
        return "dnf install wireguard-tools"
    if shutil.which("pacman"):
        return "pacman -S wireguard-tools"
    if shutil.which("zypper"):
        return "zypper install wireguard-tools"
    if shutil.which("apk"):
        return "apk add wireguard-tools"
    return "install wireguard-tools with your package manager"


def check_linux_binaries(config: ServerConfig) -> CheckResult:
    """Ensure wstunnel and wg are reachable somewhere — PATH or known dirs."""
    wstunnel = shutil.which("wstunnel")
    wg = shutil.which("wg")
    if not wstunnel and not wg:
        return CheckResult(
            name="wstunnel + wg binaries",
            status=Status.FAIL,
            detail="Neither 'wstunnel' nor 'wg' is on PATH.",
            remediation=(
                "Install the WireGuard tools and reinstall the OutWarp server "
                "bundle that ships wstunnel."
            ),
            remediation_command=_wg_tools_install_cmd(),
            fix_kind="interactive",
        )
    if not wstunnel:
        return CheckResult(
            name="wstunnel + wg binaries",
            status=Status.FAIL,
            detail="'wstunnel' not on PATH (wg is).",
            remediation="Reinstall the OutWarp server bundle.",
            remediation_command="bash <(curl -fsSL https://outwarp.dev/install.sh) server",
            fix_kind="manual",
        )
    if not wg:
        return CheckResult(
            name="wstunnel + wg binaries",
            status=Status.FAIL,
            detail="'wg' not on PATH (wstunnel is).",
            remediation="Install wireguard-tools.",
            remediation_command=_wg_tools_install_cmd(),
            fix_kind="interactive",
        )
    version = _run_linux([wg, "--version"]).stdout.strip()
    return CheckResult(
        name="wstunnel + wg binaries",
        status=Status.PASS,
        detail=f"{wstunnel}, {version or wg}",
    )


def check_linux_kmod(config: ServerConfig) -> CheckResult:
    """Verify the wireguard kernel module is available (loaded or loadable)."""
    proc = _run_linux(["modinfo", "wireguard"])
    if proc.returncode == 0:
        first = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("filename:")),
            "loaded",
        )
        return CheckResult(
            name="WireGuard kernel module",
            status=Status.PASS,
            detail=first,
        )
    return CheckResult(
        name="WireGuard kernel module",
        status=Status.FAIL,
        detail="modinfo wireguard failed — kernel module not present.",
        remediation=(
            "Install kernel headers and the wireguard kernel module: "
            "apt install wireguard."
        ),
        remediation_command="apt install wireguard",
        fix_kind="interactive",
    )


def check_linux_systemd(config: ServerConfig) -> CheckResult:
    """Both wstunnel-outwarp.service and wg-quick@wg0.service must be active."""
    services = ["wstunnel-outwarp.service", f"wg-quick@{_LINUX_WG_INTERFACE}.service"]
    states: dict[str, str] = {}
    inactive: list[str] = []
    for svc in services:
        proc = _run_linux(["systemctl", "is-active", svc])
        state = (proc.stdout.strip() or "unknown")
        states[svc] = state
        if state != "active":
            inactive.append(svc)

    if not inactive:
        return CheckResult(
            name="systemd services active",
            status=Status.PASS,
            detail=", ".join(f"{k}={v}" for k, v in states.items()),
        )

    def _fix_restart(_config: ServerConfig) -> None:
        for svc in inactive:
            subprocess.run(
                ["systemctl", "restart", svc], check=True, capture_output=True, text=True,
            )

    cmd = " && ".join(f"systemctl restart {svc}" for svc in inactive)
    return CheckResult(
        name="systemd services active",
        status=Status.FAIL,
        detail=", ".join(f"{k}={v}" for k, v in states.items()),
        remediation=f"Restart the inactive service(s): {cmd}.",
        remediation_command=cmd,
        fix_kind="auto",
        fix_callable=_fix_restart,
    )


def check_linux_listen_443(config: ServerConfig) -> CheckResult:
    """Something must be listening on the public WSS port (default 443).

    Which service that is depends on the branch: wstunnel in the self-signed
    one, Caddy in the domain one. Naming the wrong service in the remediation
    would send the admin to restart something that was never meant to hold the
    port.
    """
    proc = _run_linux(["ss", "-tlnp", f"sport = :{config.port}"])
    out = proc.stdout
    listening = any(f":{config.port}" in line for line in out.splitlines()[1:])
    if listening:
        return CheckResult(
            name=f"Listening on TCP/{config.port}",
            status=Status.PASS,
            detail=out.splitlines()[1] if len(out.splitlines()) > 1 else "listening",
        )
    service = "caddy" if config.behind_reverse_proxy else "wstunnel-outwarp.service"
    return CheckResult(
        name=f"Listening on TCP/{config.port}",
        status=Status.FAIL,
        detail=f"Nothing bound to TCP/{config.port}.",
        remediation=(
            f"Start the service that owns the public port: systemctl start {service}. "
            f"Also confirm no other service already claims port {config.port}."
        ),
        remediation_command=f"systemctl start {service}",
        fix_kind="auto",
        fix_callable=lambda _c: subprocess.run(
            ["systemctl", "start", service],
            check=True, capture_output=True, text=True,
        ),
    )


def check_linux_listen_internal_ws(config: ServerConfig) -> CheckResult:
    """In the domain branch wstunnel moves to a loopback plain-WS listener."""
    name = "wstunnel on loopback"
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail="wstunnel holds the public port directly"
        )
    port = config.internal_ws_port
    proc = _run_linux(["ss", "-tlnp", f"sport = :{port}"])
    lines = proc.stdout.splitlines()[1:]
    if any(f":{port}" in line for line in lines):
        # Binding 0.0.0.0 here would expose the un-TLS'd listener to the network
        # and let anyone who knows the path skip the front entirely.
        exposed = any("0.0.0.0" in line or "*:" in line for line in lines)
        if exposed:
            return CheckResult(
                name=name,
                status=Status.WARN,
                detail=f"TCP/{port} is bound on all interfaces, not just loopback",
                remediation=(
                    "The plain-WebSocket listener should only be reachable from Caddy. "
                    "Re-run `outwarp-server restart` to rewrite the unit."
                ),
                remediation_command="outwarp-server restart",
            )
        return CheckResult(name=name, status=Status.PASS, detail=f"127.0.0.1:{port}")
    return CheckResult(
        name=name,
        status=Status.FAIL,
        detail=f"Nothing bound to TCP/{port} — Caddy has nothing to proxy to.",
        remediation="systemctl start wstunnel-outwarp.service",
        remediation_command="systemctl start wstunnel-outwarp.service",
        fix_kind="auto",
        fix_callable=lambda _c: subprocess.run(
            ["systemctl", "start", "wstunnel-outwarp.service"],
            check=True, capture_output=True, text=True,
        ),
    )


def check_linux_listen_wg(config: ServerConfig) -> CheckResult:
    """The wstunnel→WG forwarder must bind 127.0.0.1 only (never 0.0.0.0).

    A UDP listener on 0.0.0.0:51820 means wstunnel exposed WireGuard plaintext
    to the public interface — the very thing the WSS wrapper was supposed to
    avoid. Treat that as FAIL.
    """
    proc = _run_linux(["ss", "-ulnp", f"sport = :{config.wg_listen_port}"])
    lines = [ln for ln in proc.stdout.splitlines()[1:] if ln.strip()]
    if not lines:
        return CheckResult(
            name=f"WG forwarder UDP/{config.wg_listen_port}",
            status=Status.WARN,
            detail="No UDP listener on the local WG forwarder port.",
            remediation=(
                "The wstunnel server hasn't yet opened its local WG socket — "
                "this is normal until the first client connects."
            ),
        )
    def _local_addr(line: str) -> str:
        parts = line.split()
        # ss -ulnp columns: State Recv-Q Send-Q LocalAddress:Port PeerAddress:Port [process]
        return parts[3] if len(parts) >= 4 else ""

    public = [
        ln for ln in lines
        if _local_addr(ln).startswith(("0.0.0.0:", "*:", "[::]:"))
    ]
    if public:
        return CheckResult(
            name=f"WG forwarder UDP/{config.wg_listen_port}",
            status=Status.FAIL,
            detail=f"Listener bound to a public address: {public[0]}",
            remediation=(
                "wstunnel should forward to 127.0.0.1 only. Run `outwarp-server "
                "restart` to regenerate the unit."
            ),
            remediation_command="outwarp-server restart",
            fix_kind="manual",
        )
    return CheckResult(
        name=f"WG forwarder UDP/{config.wg_listen_port}",
        status=Status.PASS,
        detail=lines[0],
    )


def _ip_forward_fix(_config: ServerConfig) -> None:
    Path(_LINUX_SYSCTL_DROP_IN).write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
    subprocess.run(
        ["sysctl", "-p", _LINUX_SYSCTL_DROP_IN], check=True, capture_output=True, text=True,
    )


def check_linux_ip_forward(config: ServerConfig) -> CheckResult:
    """Runtime ip_forward must be on AND persisted under /etc/sysctl.d."""
    runtime = _run_linux(["sysctl", "-n", "net.ipv4.ip_forward"])
    enabled = runtime.stdout.strip() == "1"

    persistent = False
    for p in Path("/etc/sysctl.d").glob("*.conf") if Path("/etc/sysctl.d").exists() else []:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == "net.ipv4.ip_forward" and value.strip() == "1":
                persistent = True
                break
        if persistent:
            break

    if enabled and persistent:
        return CheckResult(
            name="IP forwarding (net.ipv4.ip_forward)",
            status=Status.PASS,
            detail="runtime=1, persisted in /etc/sysctl.d",
        )
    if enabled and not persistent:
        return CheckResult(
            name="IP forwarding (net.ipv4.ip_forward)",
            status=Status.WARN,
            detail="runtime=1 but no /etc/sysctl.d/*.conf sets it — reverts on reboot.",
            remediation=(
                f"Persist with: echo 'net.ipv4.ip_forward=1' > {_LINUX_SYSCTL_DROP_IN} "
                f"&& sysctl -p {_LINUX_SYSCTL_DROP_IN}."
            ),
            remediation_command=(
                f"echo 'net.ipv4.ip_forward=1' > {_LINUX_SYSCTL_DROP_IN} && "
                f"sysctl -p {_LINUX_SYSCTL_DROP_IN}"
            ),
            fix_kind="auto",
            fix_callable=_ip_forward_fix,
        )
    return CheckResult(
        name="IP forwarding (net.ipv4.ip_forward)",
        status=Status.FAIL,
        detail=f"runtime={runtime.stdout.strip() or '?'}, persistent={persistent}",
        remediation=(
            f"Enable and persist with: echo 'net.ipv4.ip_forward=1' > {_LINUX_SYSCTL_DROP_IN} "
            f"&& sysctl -p {_LINUX_SYSCTL_DROP_IN}."
        ),
        remediation_command=(
            f"echo 'net.ipv4.ip_forward=1' > {_LINUX_SYSCTL_DROP_IN} && "
            f"sysctl -p {_LINUX_SYSCTL_DROP_IN}"
        ),
        fix_kind="auto",
        fix_callable=_ip_forward_fix,
    )


def _masquerade_fix(config: ServerConfig) -> None:
    from outwarp_server.platforms import get_server_platform
    from outwarp_server.wireguard import build_server_wg_conf
    get_server_platform().install_wg_config(build_server_wg_conf(config))


def check_linux_nat_masquerade(config: ServerConfig) -> CheckResult:
    """iptables nat POSTROUTING must MASQUERADE the WG subnet."""
    proc = _run_linux(["iptables", "-t", "nat", "-S", "POSTROUTING"])
    if proc.returncode != 0:
        return CheckResult(
            name="NAT MASQUERADE for WG subnet",
            status=Status.FAIL,
            detail=f"iptables query failed: {(proc.stderr or '').strip() or proc.returncode}",
            remediation="Install iptables (apt install iptables) and re-run.",
            remediation_command="apt install iptables",
            fix_kind="interactive",
        )
    needle_src = f"-s {config.subnet}"
    rule = next(
        (
            line for line in proc.stdout.splitlines()
            if needle_src in line and "MASQUERADE" in line
        ),
        None,
    )
    if rule:
        return CheckResult(
            name="NAT MASQUERADE for WG subnet",
            status=Status.PASS,
            detail=rule.strip(),
        )
    return CheckResult(
        name="NAT MASQUERADE for WG subnet",
        status=Status.FAIL,
        detail=f"No MASQUERADE rule covers {config.subnet}.",
        remediation=(
            "Re-apply the WG config (its PostUp adds the rule): outwarp-server restart."
        ),
        remediation_command="outwarp-server restart",
        fix_kind="auto",
        fix_callable=_masquerade_fix,
    )


def check_linux_fail2ban(config: ServerConfig) -> CheckResult:
    """Optional hardening — fail2ban shields the public WSS port from brute force."""
    if shutil.which("fail2ban-client"):
        return CheckResult(
            name="fail2ban present",
            status=Status.PASS,
            detail="fail2ban-client on PATH",
        )
    return CheckResult(
        name="fail2ban present",
        status=Status.WARN,
        detail="fail2ban not installed.",
        remediation=(
            "Optional but recommended for public servers: apt install fail2ban."
        ),
        remediation_command="apt install fail2ban",
        fix_kind="interactive",
    )


def check_linux_reverse_dns(config: ServerConfig) -> CheckResult:
    """Reverse DNS should round-trip to the configured endpoint hostname.

    Skipped if the endpoint is an IP literal — there's no expectation that an
    IP should rDNS to itself.
    """
    endpoint = config.endpoint.strip()
    try:
        socket.inet_aton(endpoint)
        is_ip = True
    except OSError:
        is_ip = False
    if is_ip:
        return CheckResult(
            name="Reverse DNS",
            status=Status.SKIP,
            detail=f"endpoint is an IP literal ({endpoint}) — rDNS check N/A.",
        )
    try:
        public_ip = socket.gethostbyname(endpoint)
    except socket.gaierror as exc:
        return CheckResult(
            name="Reverse DNS",
            status=Status.FAIL,
            detail=f"Forward lookup of {endpoint} failed: {exc}",
        )
    try:
        rdns_name, _, _ = socket.gethostbyaddr(public_ip)
    except socket.herror as exc:
        return CheckResult(
            name="Reverse DNS",
            status=Status.WARN,
            detail=f"rDNS for {public_ip} not configured: {exc}",
            remediation="Ask your hosting provider to set a PTR record. Not fatal.",
        )
    if endpoint.lower() == rdns_name.lower():
        return CheckResult(
            name="Reverse DNS",
            status=Status.PASS,
            detail=f"{public_ip} → {rdns_name}",
        )
    return CheckResult(
        name="Reverse DNS",
        status=Status.WARN,
        detail=f"{public_ip} → {rdns_name} ≠ {endpoint}",
        remediation="Endpoint hostname does not match PTR record. Cosmetic only.",
    )


# ───────── orchestration ─────────

def gather_checks() -> list[Check]:
    common = [
        Check("config", "Config", check_config_loadable),
        Check("clients", "Config", check_clients_registered),
        Check("tls", "Config", check_tls_cert_files),
        Check("caddy", "Transport", check_caddy_front),
        Check("public_cert", "Transport", check_public_certificate),
        Check("egress", "Network", check_egress),
    ]
    if sys.platform == "win32":
        return common + [
            Check("admin", "Permissions", check_win_admin),
            Check("ip_forwarding", "Network", check_win_ip_forwarding),
            Check("iface_forwarding", "Network", check_win_forwarding_on_wg_iface),
            Check("netnat_provider", "NAT", check_win_netnat_provider),
            Check("netnat", "NAT", check_win_netnat),
            Check("winnat_svc", "NAT", check_win_winnat_service),
            Check("wg_svc", "WireGuard", check_win_wg_service),
            Check("wstunnel_proc", "wstunnel", check_win_wstunnel_running),
            Check("listen", "wstunnel", check_win_listening_port),
            Check("firewall", "Firewall", check_win_firewall),
        ]
    if sys.platform.startswith("linux"):
        return common + [
            Check("linux_binaries", "Binaries", check_linux_binaries),
            Check("linux_kmod", "WireGuard", check_linux_kmod),
            Check("linux_systemd", "Services", check_linux_systemd),
            Check("linux_listen_443", "wstunnel", check_linux_listen_443),
            Check("linux_listen_internal_ws", "wstunnel", check_linux_listen_internal_ws),
            Check("linux_listen_wg", "wstunnel", check_linux_listen_wg),
            Check("linux_ip_forward", "Network", check_linux_ip_forward),
            Check("linux_nat_masquerade", "NAT", check_linux_nat_masquerade),
            Check("linux_fail2ban", "Hardening", check_linux_fail2ban),
            Check("linux_reverse_dns", "DNS", check_linux_reverse_dns),
        ]
    return common


def run_all(config: ServerConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in gather_checks():
        try:
            results.append(check.runner(config))
        except Exception as exc:
            log.exception("Diagnostics check %r raised", check.key)
            results.append(
                CheckResult(
                    name=check.key,
                    status=Status.FAIL,
                    detail=f"Check crashed: {exc}",
                )
            )
    return results
