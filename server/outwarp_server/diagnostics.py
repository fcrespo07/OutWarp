from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from outwarp_server.config import ServerConfig, default_config_dir

log = logging.getLogger(__name__)


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    remediation: str | None = None
    # Bare command intended for the UI's "Copy" button — without surrounding
    # prose like "As admin: ...". Falls back to `remediation` when unset.
    remediation_command: str | None = None


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
            "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' "
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


# ───────── orchestration ─────────

def gather_checks() -> list[Check]:
    common = [
        Check("config", "Config", check_config_loadable),
        Check("clients", "Config", check_clients_registered),
        Check("tls", "Config", check_tls_cert_files),
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
