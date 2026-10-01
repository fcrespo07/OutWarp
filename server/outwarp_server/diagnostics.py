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
from outwarp_server.i18n import t

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
        name=t("dx.config.name"),
        status=Status.PASS,
        detail=t(
            "dx.config.detail", endpoint=config.endpoint, port=config.port, subnet=config.subnet
        ),
    )


def check_clients_registered(config: ServerConfig) -> CheckResult:
    if not config.clients:
        return CheckResult(
            name=t("dx.clients.name"),
            status=Status.WARN,
            detail=t("dx.clients.none"),
            remediation=t("dx.clients.none_fix"),
            remediation_command="outwarp-server add-client <name>",
        )
    return CheckResult(
        name=t("dx.clients.name"),
        status=Status.PASS,
        detail=t("dx.clients.count", n=len(config.clients)),
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
            name=t("dx.tls.name"),
            status=Status.FAIL,
            detail=t("dx.tls.missing", files=", ".join(str(p) for p in missing)),
            remediation=t("dx.tls.fix"),
            remediation_command="outwarp-server setup",
        )
    return CheckResult(
        name=t("dx.tls.name"),
        status=Status.PASS,
        detail=str(cert.parent),
    )


def check_caddy_front(config: ServerConfig) -> CheckResult:
    """In the domain branch, Caddy is the thing holding the public port."""
    from outwarp_server import caddy

    name = t("dx.caddy.name")
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail=t("dx.caddy.selfsigned")
        )

    if caddy.find_caddy() is None:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=t("dx.caddy.missing"),
            remediation=t("dx.caddy.install_fix", hint=caddy.install_hint()),
            remediation_command=caddy.install_hint(),
            fix_kind="interactive",
        )
    if not caddy.CADDY_SITE_FILE.exists():
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=t("dx.caddy.site_missing", path=caddy.CADDY_SITE_FILE),
            remediation=t("dx.caddy.setup_fix"),
            remediation_command="outwarp-server setup",
        )
    ok, detail = caddy.validate()
    if not ok:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=t("dx.caddy.invalid", detail=detail),
            remediation=t("dx.caddy.invalid_fix"),
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

    name = t("dx.cert.name")
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail=t("dx.cert.selfsigned")
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
            remediation=t("dx.cert.untrusted_fix", port=config.port),
            remediation_command="journalctl -u caddy -e",
        )
    except OSError as exc:
        return CheckResult(
            name=name,
            status=Status.WARN,
            detail=t("dx.cert.unreachable", endpoint=config.endpoint, port=config.port, error=exc),
            remediation=t("dx.cert.unreachable_fix"),
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
            name=t("dx.egress.name"),
            status=Status.FAIL,
            detail=t("dx.egress.fail", error=exc),
            remediation=t("dx.egress.fix"),
        )
    return CheckResult(
        name=t("dx.egress.name"),
        status=Status.PASS,
        detail=t("dx.egress.ok"),
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
            name=t("dx.win.admin_name"),
            status=Status.FAIL,
            detail=t("dx.win.admin_detail"),
            remediation=t("dx.win.admin_fix"),
        )
    return CheckResult(name=t("dx.win.admin_name"), status=Status.PASS)


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
            name=t("dx.win.ipfwd_name"),
            status=Status.FAIL,
            detail=t("dx.win.registry", error=exc),
        )
    if int(value) == 1:
        return CheckResult(
            name=t("dx.win.ipfwd_name"),
            status=Status.PASS,
            detail="IPEnableRouter = 1",
        )
    return CheckResult(
        name=t("dx.win.ipfwd_name"),
        status=Status.FAIL,
        detail=f"IPEnableRouter = {value}",
        remediation=t(
            "dx.win.ipfwd_fix",
            cmd="Set-ItemProperty -Path "
            "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' "
            "-Name IPEnableRouter -Value 1",
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
            name=t("dx.win.ifacefwd_name", iface=_WIN_WG_INTERFACE),
            status=Status.FAIL,
            detail=t("dx.win.iface_absent"),
            remediation=t("dx.win.iface_fix"),
            remediation_command="outwarp-server restart",
        )
    if "Enabled" in stdout:
        return CheckResult(
            name=t("dx.win.ifacefwd_name", iface=_WIN_WG_INTERFACE),
            status=Status.PASS,
            detail=t("dx.win.enabled"),
        )
    return CheckResult(
        name=t("dx.win.ifacefwd_name", iface=_WIN_WG_INTERFACE),
        status=Status.FAIL,
        detail=stdout,
        remediation=t(
            "dx.win.ifacefwd_fix",
            cmd=f"Set-NetIPInterface -InterfaceAlias '{_WIN_WG_INTERFACE}' -Forwarding Enabled",
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
        return CheckResult(name=t("dx.win.provider_name"), status=Status.PASS)
    return CheckResult(
        name=t("dx.win.provider_name"),
        status=Status.FAIL,
        detail=t("dx.win.provider_detail"),
        remediation=t("dx.win.provider_fix"),
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
            name=t("dx.win.netnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.netnat_noprov"),
            remediation=t("dx.win.netnat_noprov_fix"),
            remediation_command=(
                "Enable-WindowsOptionalFeature -Online -FeatureName Containers -All"
            ),
        )
    if not raw:
        return CheckResult(
            name=t("dx.win.netnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.netnat_none"),
            remediation=t(
                "dx.win.netnat_none_fix",
                cmd=f"New-NetNat -Name '{_WIN_NAT_NAME}' "
                f"-InternalIPInterfaceAddressPrefix '{config.subnet}'",
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
            name=t("dx.win.netnat_name"),
            status=Status.WARN,
            detail=t("dx.win.netnat_unparseable", raw=raw[:200]),
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
            name=t("dx.win.netnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.netnat_nomatch", subnet=config.subnet, listing=listing),
            remediation=t("dx.win.netnat_conflict_fix"),
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
            name=t("dx.win.netnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.netnat_inactive", name=found.get("Name")),
            remediation=t("dx.win.netnat_inactive_fix"),
            remediation_command="Restart-Service WinNat",
        )
    if others:
        listing = ", ".join(
            f"{n.get('Name')}({n.get('InternalIPInterfaceAddressPrefix')})" for n in others
        )
        return CheckResult(
            name=t("dx.win.netnat_name"),
            status=Status.WARN,
            detail=t("dx.win.netnat_extra", subnet=config.subnet, listing=listing),
            remediation=t("dx.win.netnat_extra_fix"),
        )
    return CheckResult(
        name=t("dx.win.netnat_name"),
        status=Status.PASS,
        detail=t("dx.win.netnat_ok", name=found.get("Name"), subnet=config.subnet),
    )


def check_win_winnat_service(config: ServerConfig) -> CheckResult:
    out = _sc("query", "WinNat").stdout
    if "RUNNING" in out:
        return CheckResult(name=t("dx.win.winnat_name"), status=Status.PASS, detail="RUNNING")
    if "STOPPED" in out:
        # NetNat creation triggers WinNat on demand, but only if startup is not
        # disabled. If `Start-Service` fails here, the underlying driver is
        # missing — almost always because Hyper-V / Containers features aren't
        # enabled. Suggest both the easy path and the diagnostic.
        return CheckResult(
            name=t("dx.win.winnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.winnat_stopped"),
            remediation=t("dx.win.winnat_stopped_fix"),
            remediation_command=(
                "Set-Service WinNat -StartupType Automatic; Start-Service WinNat"
            ),
        )
    if "FAILED" in out or not out.strip():
        # `sc query` returns "[SC] EnumQueryServicesStatus:OpenService FAILED 1060"
        # when the service literally doesn't exist on the machine.
        return CheckResult(
            name=t("dx.win.winnat_name"),
            status=Status.FAIL,
            detail=t("dx.win.winnat_missing"),
            remediation=t("dx.win.winnat_missing_fix"),
            remediation_command=(
                "Enable-WindowsOptionalFeature -Online -FeatureName Containers -All"
            ),
        )
    return CheckResult(
        name=t("dx.win.winnat_name"),
        status=Status.WARN,
        detail=t("dx.win.winnat_unknown", state=out.strip()[:200]),
    )


def check_win_wg_service(config: ServerConfig) -> CheckResult:
    out = _sc("query", f"WireGuardTunnel${_WIN_WG_INTERFACE}").stdout
    if "RUNNING" in out:
        return CheckResult(
            name=t("dx.win.wgsvc_name"),
            status=Status.PASS,
            detail=f"WireGuardTunnel${_WIN_WG_INTERFACE}: RUNNING",
        )
    return CheckResult(
        name=t("dx.win.wgsvc_name"),
        status=Status.FAIL,
        detail=t("dx.win.wgsvc_down", state=out.strip()[:200]),
        remediation=t("dx.win.restart_fix"),
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
        return CheckResult(
            name=t("dx.win.wstunnel_name"), status=Status.PASS, detail=t("dx.win.running")
        )
    return CheckResult(
        name=t("dx.win.wstunnel_name"),
        status=Status.FAIL,
        detail=t("dx.win.wstunnel_none"),
        remediation=t("dx.win.wstunnel_fix"),
    )


def check_win_listening_port(config: ServerConfig) -> CheckResult:
    result = _ps(
        f"Get-NetTCPConnection -State Listen -LocalPort {config.port} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess"
    )
    pid_str = result.stdout.strip()
    if not pid_str:
        return CheckResult(
            name=t("dx.listen_name", port=config.port),
            status=Status.FAIL,
            detail=t("dx.win.listen_none"),
            remediation=t("dx.win.listen_fix"),
        )
    return CheckResult(
        name=t("dx.listen_name", port=config.port),
        status=Status.PASS,
        detail=t("dx.win.pid", pid=pid_str),
    )


def check_win_enroll_listener(config: ServerConfig) -> CheckResult:
    """Same contract as check_linux_enroll_listener: up, loopback only."""
    name = t("dx.enroll_name", port=config.enroll_port)
    result = _ps(
        f"Get-NetTCPConnection -State Listen -LocalPort {config.enroll_port} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty LocalAddress"
    )
    addr = result.stdout.strip()
    if not addr:
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=t("dx.win.enroll_none"),
            remediation=t("dx.win.enroll_none_fix"),
        )
    if addr not in ("127.0.0.1", "::1"):
        return CheckResult(
            name=name,
            status=Status.WARN,
            detail=t("dx.win.enroll_public", addr=addr),
            remediation=t("dx.win.enroll_public_fix"),
        )
    return CheckResult(name=name, status=Status.PASS, detail=f"{addr}:{config.enroll_port}")


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
                name=t("dx.win.fw_name"),
                status=Status.WARN,
                detail=t("dx.win.fw_unparseable", raw=raw[:200]),
            )
        entries = data if isinstance(data, list) else [data]
        enabled_values = {str(e.get("Enabled")).lower() for e in entries}
        if "true" in enabled_values or "1" in enabled_values:
            return CheckResult(
                name=t("dx.win.fw_name"),
                status=Status.PASS,
                detail=t("dx.win.fw_enabled"),
            )
        return CheckResult(
            name=t("dx.win.fw_name"),
            status=Status.FAIL,
            detail=t("dx.win.fw_disabled", raw=raw),
            remediation=t(
                "dx.win.fw_disabled_fix",
                cmd="Enable-NetFirewallRule -DisplayName 'OutWarp-wstunnel'",
            ),
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
            name=t("dx.win.fw_name"),
            status=Status.PASS,
            detail=t("dx.win.fw_netsh"),
        )
    return CheckResult(
        name=t("dx.win.fw_name"),
        status=Status.WARN,
        detail=t("dx.win.fw_none"),
        remediation=t(
            "dx.win.fw_none_fix",
            cmd="netsh advfirewall firewall add rule name=OutWarp-wstunnel "
            f"dir=in action=allow localport={config.port} protocol=TCP",
        ),
        remediation_command=(
            f"netsh advfirewall firewall add rule name=OutWarp-wstunnel "
            f"dir=in action=allow localport={config.port} protocol=TCP"
        ),
    )


# ───────── Linux ─────────

_LINUX_WG_INTERFACE = "wg0"
_LINUX_SYSCTL_DROP_IN = "/etc/sysctl.d/99-outwarp.conf"
_IP_FORWARD_CMD = (
    f"echo 'net.ipv4.ip_forward=1' > {_LINUX_SYSCTL_DROP_IN} && "
    f"sysctl -p {_LINUX_SYSCTL_DROP_IN}"
)


def _run_linux(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout,
    )


def _has_systemd() -> bool:
    """True on a native systemd host; false in a container (Docker/K8s), where
    ServerManager/KubernetesServerPlatform supervise wstunnel and WireGuard
    directly instead. Checking for the runtime directory (not just the
    `systemctl` binary) avoids false positives in chroots/WSL that ship the
    binary without systemd actually running as PID 1.
    """
    return Path("/run/systemd/system").exists() and shutil.which("systemctl") is not None


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
            name=t("dx.linux.bins_name"),
            status=Status.FAIL,
            detail=t("dx.linux.bins_none"),
            remediation=t("dx.linux.bins_none_fix"),
            remediation_command=_wg_tools_install_cmd(),
            fix_kind="interactive",
        )
    if not wstunnel:
        return CheckResult(
            name=t("dx.linux.bins_name"),
            status=Status.FAIL,
            detail=t("dx.linux.bins_nowstunnel"),
            remediation=t("dx.linux.bins_nowstunnel_fix"),
            remediation_command="bash <(curl -fsSL https://outwarp.dev/install.sh) server",
            fix_kind="manual",
        )
    if not wg:
        return CheckResult(
            name=t("dx.linux.bins_name"),
            status=Status.FAIL,
            detail=t("dx.linux.bins_nowg"),
            remediation=t("dx.linux.bins_nowg_fix"),
            remediation_command=_wg_tools_install_cmd(),
            fix_kind="interactive",
        )
    version = _run_linux([wg, "--version"]).stdout.strip()
    return CheckResult(
        name=t("dx.linux.bins_name"),
        status=Status.PASS,
        detail=f"{wstunnel}, {version or wg}",
    )


def check_linux_kmod(config: ServerConfig) -> CheckResult:
    """Verify the wireguard kernel module is available (loaded or loadable).

    `modinfo` inspects /lib/modules/<running-kernel>/ for the host kernel —
    that tree lives on the node, not inside a container image, so `modinfo`
    is typically missing entirely in Docker/K8s (and would report a false
    negative even if installed, since the host's module directory isn't
    mounted in). There the live WireGuard interface itself — which can only
    exist if the node's kernel module is loaded — is the reliable signal.
    """
    try:
        proc = _run_linux(["modinfo", "wireguard"])
    except FileNotFoundError:
        pass
    else:
        if proc.returncode == 0:
            first = next(
                (ln for ln in proc.stdout.splitlines() if ln.startswith("filename:")),
                "loaded",
            )
            return CheckResult(
                name=t("dx.linux.kmod_name"),
                status=Status.PASS,
                detail=first,
            )
        return CheckResult(
            name=t("dx.linux.kmod_name"),
            status=Status.FAIL,
            detail=t("dx.linux.kmod_missing"),
            remediation=t("dx.linux.kmod_missing_fix"),
            remediation_command="apt install wireguard",
            fix_kind="interactive",
        )

    proc = _run_linux(["ip", "-o", "link", "show", "type", "wireguard"])
    if proc.returncode == 0 and proc.stdout.strip():
        iface = proc.stdout.split(":", 2)[1].strip() if ":" in proc.stdout else "wireguard"
        return CheckResult(
            name=t("dx.linux.kmod_name"),
            status=Status.PASS,
            detail=t("dx.linux.kmod_container", iface=iface),
        )
    return CheckResult(
        name=t("dx.linux.kmod_name"),
        status=Status.FAIL,
        detail=t("dx.linux.kmod_unknown"),
        remediation=t("dx.linux.kmod_unknown_fix"),
        remediation_command="modprobe wireguard",
        fix_kind="manual",
    )


def _enroll_unit_installed() -> bool:
    from outwarp_server.platforms.linux import _ENROLL_SERVICE_PATH
    return _ENROLL_SERVICE_PATH.exists()


def check_linux_systemd(config: ServerConfig) -> CheckResult:
    """Both wstunnel-outwarp.service and wg-quick@wg0.service must be active.

    Only meaningful on a native systemd install. In a container (Docker/K8s)
    there is no systemd at all — ServerManager runs wstunnel as a plain
    subprocess and KubernetesServerPlatform brings WireGuard up directly via
    wg-quick — so this check doesn't apply; check_linux_listen_443 and
    check_linux_listen_wg already cover the equivalent "is it actually
    running" question for that platform.
    """
    if not _has_systemd():
        return CheckResult(
            name=t("dx.linux.systemd_name"),
            status=Status.SKIP,
            detail=t("dx.linux.systemd_none"),
        )
    services = [
        "wstunnel-outwarp.service",
        f"wg-quick@{_LINUX_WG_INTERFACE}.service",
        "outwarp-enroll.service",
    ]
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
            name=t("dx.linux.systemd_name"),
            status=Status.PASS,
            detail=", ".join(f"{k}={v}" for k, v in states.items()),
        )

    if "outwarp-enroll.service" in inactive and not _enroll_unit_installed():
        # Installs from before the listener had a unit (< 0.13): `restart`
        # (re)writes every unit from the current code, a plain systemctl
        # restart of a unit that does not exist cannot.
        return CheckResult(
            name=t("dx.linux.systemd_name"),
            status=Status.FAIL,
            detail=", ".join(f"{k}={v}" for k, v in states.items()),
            remediation=t("dx.linux.systemd_noenroll_fix"),
            remediation_command="outwarp-server restart",
            fix_kind="manual",
        )

    def _fix_restart(_config: ServerConfig) -> None:
        for svc in inactive:
            subprocess.run(
                ["systemctl", "restart", svc], check=True, capture_output=True, text=True,
            )

    cmd = " && ".join(f"systemctl restart {svc}" for svc in inactive)
    return CheckResult(
        name=t("dx.linux.systemd_name"),
        status=Status.FAIL,
        detail=", ".join(f"{k}={v}" for k, v in states.items()),
        remediation=t("dx.linux.systemd_fix", cmd=cmd),
        remediation_command=cmd,
        fix_kind="auto",
        fix_callable=_fix_restart,
    )


def _ss_local_addr(line: str) -> str:
    """Local Address:Port column of an `ss -lnp` row.

    `ss` prints the peer column as `0.0.0.0:*` for every listener, so a plain
    substring test for "0.0.0.0" flags loopback sockets as public too.
    """
    parts = line.split()
    # State Recv-Q Send-Q Local:Port Peer:Port [process]
    return parts[3] if len(parts) >= 4 else ""


def _bound_publicly(line: str) -> bool:
    return _ss_local_addr(line).startswith(("0.0.0.0:", "*:", "[::]:"))


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
            name=t("dx.listen_name", port=config.port),
            status=Status.PASS,
            detail=out.splitlines()[1] if len(out.splitlines()) > 1 else t("dx.linux.listening"),
        )
    if not _has_systemd():
        return CheckResult(
            name=t("dx.listen_name", port=config.port),
            status=Status.FAIL,
            detail=t("dx.linux.listen_none", port=config.port),
            remediation=t("dx.linux.listen_none_container_fix"),
            remediation_command="kubectl rollout restart deployment/outwarp-server",
            fix_kind="manual",
        )
    service = "caddy" if config.behind_reverse_proxy else "wstunnel-outwarp.service"
    return CheckResult(
        name=t("dx.listen_name", port=config.port),
        status=Status.FAIL,
        detail=t("dx.linux.listen_none", port=config.port),
        remediation=t("dx.linux.listen_none_fix", service=service, port=config.port),
        remediation_command=f"systemctl start {service}",
        fix_kind="auto",
        fix_callable=lambda _c: subprocess.run(
            ["systemctl", "start", service],
            check=True, capture_output=True, text=True,
        ),
    )


def check_linux_listen_internal_ws(config: ServerConfig) -> CheckResult:
    """In the domain branch wstunnel moves to a loopback plain-WS listener."""
    name = t("dx.linux.loopback_name")
    if not config.behind_reverse_proxy:
        return CheckResult(
            name=name, status=Status.SKIP, detail=t("dx.linux.loopback_direct")
        )
    port = config.internal_ws_port
    proc = _run_linux(["ss", "-tlnp", f"sport = :{port}"])
    lines = proc.stdout.splitlines()[1:]
    if any(f":{port}" in line for line in lines):
        # Binding 0.0.0.0 here would expose the un-TLS'd listener to the network
        # and let anyone who knows the path skip the front entirely.
        exposed = any(_bound_publicly(line) for line in lines)
        if exposed:
            return CheckResult(
                name=name,
                status=Status.WARN,
                detail=t("dx.linux.loopback_exposed", port=port),
                remediation=t("dx.linux.loopback_exposed_fix"),
                remediation_command="outwarp-server restart",
            )
        return CheckResult(name=name, status=Status.PASS, detail=f"127.0.0.1:{port}")
    return CheckResult(
        name=name,
        status=Status.FAIL,
        detail=t("dx.linux.loopback_none", port=port),
        remediation=t("dx.linux.loopback_none_fix"),
        remediation_command="systemctl start wstunnel-outwarp.service",
        fix_kind="auto",
        fix_callable=lambda _c: subprocess.run(
            ["systemctl", "start", "wstunnel-outwarp.service"],
            check=True, capture_output=True, text=True,
        ),
    )


def check_linux_enroll_listener(config: ServerConfig) -> CheckResult:
    """The enrolment listener must be up, and on loopback only.

    It is what turns an `add-client` profile into a registered peer; without
    it every enrolment import fails with "could not reach the enrolment
    endpoint" even though the tunnel port is wide open (B-018). It is reached
    through wstunnel's restricted forward, so a public bind means an install
    from before 0.13 is still exposing it with its own TLS on a port nobody
    needs open any more.
    """
    name = t("dx.enroll_name", port=config.enroll_port)
    proc = _run_linux(["ss", "-tlnp", f"sport = :{config.enroll_port}"])
    lines = [ln for ln in proc.stdout.splitlines()[1:] if ln.strip()]
    if lines:
        if any(_bound_publicly(ln) for ln in lines):
            return CheckResult(
                name=name,
                status=Status.WARN,
                detail=t("dx.linux.loopback_exposed", port=config.enroll_port),
                remediation=t("dx.linux.enroll_public_fix"),
                remediation_command="outwarp-server restart",
            )
        return CheckResult(name=name, status=Status.PASS, detail=f"127.0.0.1:{config.enroll_port}")
    if not _has_systemd():
        return CheckResult(
            name=name,
            status=Status.FAIL,
            detail=t("dx.linux.enroll_none", port=config.enroll_port),
            remediation=t("dx.linux.enroll_none_container_fix"),
            remediation_command="kubectl rollout restart deployment/outwarp-server",
            fix_kind="manual",
        )
    return CheckResult(
        name=name,
        status=Status.FAIL,
        detail=t("dx.linux.enroll_none", port=config.enroll_port),
        remediation=t("dx.linux.enroll_none_fix"),
        remediation_command="systemctl start outwarp-enroll.service",
        fix_kind="auto",
        fix_callable=lambda _c: subprocess.run(
            ["systemctl", "start", "outwarp-enroll.service"],
            check=True, capture_output=True, text=True,
        ),
    )


def check_linux_listen_wg(config: ServerConfig) -> CheckResult:
    """The wstunnel→WG forwarder must bind 127.0.0.1 only (never 0.0.0.0).

    A UDP listener on 0.0.0.0:51820 means wstunnel exposed WireGuard plaintext
    to the public interface — the very thing the WSS wrapper was supposed to
    avoid. Treat that as FAIL.

    Exception: KubernetesServerPlatform (and any no-systemd deploy) brings
    WireGuard up via wg-quick directly — kernel WireGuard has no per-interface
    bind-address option, `wg set <iface> listen-port` always opens on every
    interface. `outwarp-server restart` cannot change that, so a bare FAIL
    there is a dead end. Downgrade to WARN with the real mitigation: block
    external access to this UDP port at the host/router firewall instead.
    """
    proc = _run_linux(["ss", "-ulnp", f"sport = :{config.wg_listen_port}"])
    lines = [ln for ln in proc.stdout.splitlines()[1:] if ln.strip()]
    if not lines:
        return CheckResult(
            name=t("dx.linux.wgfwd_name", port=config.wg_listen_port),
            status=Status.WARN,
            detail=t("dx.linux.wgfwd_none"),
            remediation=t("dx.linux.wgfwd_none_fix"),
        )
    public = [ln for ln in lines if _bound_publicly(ln)]
    if public:
        if not _has_systemd():
            return CheckResult(
                name=t("dx.linux.wgfwd_name", port=config.wg_listen_port),
                status=Status.WARN,
                detail=t("dx.linux.wgfwd_public_container", addr=public[0]),
                remediation=t("dx.linux.wgfwd_public_container_fix", port=config.wg_listen_port),
                fix_kind="manual",
            )
        return CheckResult(
            name=t("dx.linux.wgfwd_name", port=config.wg_listen_port),
            status=Status.FAIL,
            detail=t("dx.linux.wgfwd_public", addr=public[0]),
            remediation=t("dx.linux.wgfwd_public_fix"),
            remediation_command="outwarp-server restart",
            fix_kind="manual",
        )
    return CheckResult(
        name=t("dx.linux.wgfwd_name", port=config.wg_listen_port),
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
            name=t("dx.linux.ipfwd_name"),
            status=Status.PASS,
            detail=t("dx.linux.ipfwd_ok"),
        )
    if enabled and not persistent:
        return CheckResult(
            name=t("dx.linux.ipfwd_name"),
            status=Status.WARN,
            detail=t("dx.linux.ipfwd_volatile"),
            remediation=t("dx.linux.ipfwd_volatile_fix", cmd=_IP_FORWARD_CMD),
            remediation_command=_IP_FORWARD_CMD,
            fix_kind="auto",
            fix_callable=_ip_forward_fix,
        )
    return CheckResult(
        name=t("dx.linux.ipfwd_name"),
        status=Status.FAIL,
        detail=f"runtime={runtime.stdout.strip() or '?'}, persistent={persistent}",
        remediation=t("dx.linux.ipfwd_off_fix", cmd=_IP_FORWARD_CMD),
        remediation_command=_IP_FORWARD_CMD,
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
            name=t("dx.linux.masq_name"),
            status=Status.FAIL,
            detail=t("dx.linux.masq_query", error=(proc.stderr or "").strip() or proc.returncode),
            remediation=t("dx.linux.masq_query_fix"),
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
            name=t("dx.linux.masq_name"),
            status=Status.PASS,
            detail=rule.strip(),
        )
    return CheckResult(
        name=t("dx.linux.masq_name"),
        status=Status.FAIL,
        detail=t("dx.linux.masq_none", subnet=config.subnet),
        remediation=t("dx.linux.masq_none_fix"),
        remediation_command="outwarp-server restart",
        fix_kind="auto",
        fix_callable=_masquerade_fix,
    )


def check_linux_fail2ban(config: ServerConfig) -> CheckResult:
    """Optional hardening — fail2ban shields the public WSS port from brute force."""
    if shutil.which("fail2ban-client"):
        return CheckResult(
            name=t("dx.linux.f2b_name"),
            status=Status.PASS,
            detail=t("dx.linux.f2b_ok"),
        )
    return CheckResult(
        name=t("dx.linux.f2b_name"),
        status=Status.WARN,
        detail=t("dx.linux.f2b_none"),
        remediation=t("dx.linux.f2b_fix"),
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
            name=t("dx.linux.rdns_name"),
            status=Status.SKIP,
            detail=t("dx.linux.rdns_ip", endpoint=endpoint),
        )
    try:
        public_ip = socket.gethostbyname(endpoint)
    except socket.gaierror as exc:
        return CheckResult(
            name=t("dx.linux.rdns_name"),
            status=Status.FAIL,
            detail=t("dx.linux.rdns_forward", endpoint=endpoint, error=exc),
        )
    try:
        rdns_name, _, _ = socket.gethostbyaddr(public_ip)
    except socket.herror as exc:
        return CheckResult(
            name=t("dx.linux.rdns_name"),
            status=Status.WARN,
            detail=t("dx.linux.rdns_none", ip=public_ip, error=exc),
            remediation=t("dx.linux.rdns_none_fix"),
        )
    if endpoint.lower() == rdns_name.lower():
        return CheckResult(
            name=t("dx.linux.rdns_name"),
            status=Status.PASS,
            detail=f"{public_ip} → {rdns_name}",
        )
    return CheckResult(
        name=t("dx.linux.rdns_name"),
        status=Status.WARN,
        detail=f"{public_ip} → {rdns_name} ≠ {endpoint}",
        remediation=t("dx.linux.rdns_mismatch_fix"),
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
            Check("enroll_listener", "Enrolment", check_win_enroll_listener),
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
            Check("linux_enroll_listener", "Enrolment", check_linux_enroll_listener),
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
                    detail=t("dx.check_crashed", error=exc),
                )
            )
    return results
