from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from outwarp_server.config import _atomic_write_secret
from outwarp_server.platforms.base import (
    PlatformError,
    PrerequisiteResult,
    PrerequisiteStatus,
    ServerPlatform,
)

log = logging.getLogger(__name__)

_WG_EXE = Path(r"C:\Program Files\WireGuard\wireguard.exe")
_WG_DIR = Path(r"C:\ProgramData\WireGuard")
_WG_INTERFACE = "OutWarp-Server"
_NAT_NAME = "OutWarp"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(*cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    log.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        check=check,
        creationflags=_NO_WINDOW,
    )


def _ps(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell -Command snippet."""
    return _run(
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", *args,
        check=check,
    )


class WindowsServerPlatform(ServerPlatform):
    # ── wstunnel ─────────────────────────────────────────────────────────────
    # On Windows, wstunnel runs as a subprocess owned by ServerManager.
    # These methods are intentional no-ops / read-only queries.

    def install_wstunnel_service(
        self,
        port: int,
        cert_path: Path,
        key_path: Path,
        upgrade_path: str,
        wg_listen_port: int,
        wstunnel_bin: Path,
    ) -> None:
        log.debug("install_wstunnel_service: no-op on Windows (ServerManager owns wstunnel)")

    def uninstall_wstunnel_service(self) -> None:
        log.debug("uninstall_wstunnel_service: no-op on Windows")

    def is_wstunnel_running(self) -> bool:
        result = _run("tasklist", "/FI", "IMAGENAME eq wstunnel.exe", "/NH", check=False)
        return "wstunnel" in result.stdout.lower()

    def restart_wstunnel_service(self) -> None:
        raise PlatformError(
            "Use ServerManager.restart() to restart wstunnel on Windows"
        )

    # ── WireGuard ─────────────────────────────────────────────────────────────

    def install_wg_config(self, conf_text: str, interface: str = _WG_INTERFACE) -> None:
        self._require_wireguard()
        conf_path = self.wg_config_dir() / f"{interface}.conf"
        try:
            # Atomic replace so wireguard.exe never reads a half-written conf;
            # the file (which holds the server private key) lives under
            # C:\ProgramData\WireGuard, whose ACLs WireGuard for Windows locks down.
            _atomic_write_secret(conf_path, conf_text)
        except OSError as exc:
            raise PlatformError(f"Failed to write WireGuard config: {exc}") from exc

        # Remove any stale service first so /installtunnelservice can succeed.
        if "RUNNING" in _run("sc", "query", f"WireGuardTunnel${interface}", check=False).stdout:
            log.debug("WireGuard tunnel '%s' already running; reinstalling", interface)
            _run(str(_WG_EXE), "/uninstalltunnelservice", interface, check=False)
            self._wait_service_gone(interface)

        result = _run(str(_WG_EXE), "/installtunnelservice", str(conf_path), check=False)
        if result.returncode != 0:
            raise PlatformError(
                f"wireguard.exe /installtunnelservice failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        self._wait_service_running(interface)
        log.info("WireGuard server interface '%s' installed and running", interface)

    def reload_wg(self, interface: str = _WG_INTERFACE) -> None:
        # WireGuard for Windows does not ship wg-quick or wg strip; do a full restart.
        self.restart_wg(interface)

    def is_wg_active(self, interface: str = _WG_INTERFACE) -> bool:
        result = _run("sc", "query", f"WireGuardTunnel${interface}", check=False)
        return "RUNNING" in result.stdout

    def uninstall_wg_config(self, interface: str = _WG_INTERFACE) -> None:
        if _WG_EXE.exists():
            _run(str(_WG_EXE), "/uninstalltunnelservice", interface, check=False)
            self._wait_service_gone(interface)
        self._remove_nat()
        conf_path = self.wg_config_dir() / f"{interface}.conf"
        conf_path.unlink(missing_ok=True)

    def restart_wg(self, interface: str = _WG_INTERFACE) -> None:
        conf_path = self.wg_config_dir() / f"{interface}.conf"
        if not conf_path.exists():
            raise PlatformError(f"WireGuard config not found: {conf_path}")
        conf_text = conf_path.read_text(encoding="utf-8")
        self.uninstall_wg_config(interface)
        self.install_wg_config(conf_text, interface)

    def wg_config_dir(self) -> Path:
        return _WG_DIR

    def wg_interface_name(self) -> str:
        return _WG_INTERFACE

    # ── System preparation ────────────────────────────────────────────────────

    def prepare_system(self, subnet: str, wss_port: int) -> None:
        """Enable IP routing and create NAT for the WireGuard subnet."""
        self._enable_ip_forwarding()
        self._create_nat(subnet)
        self._add_firewall_rule(wss_port)

    # Features that ship the MSFT_NetNat WMI provider. Tried in order: the
    # 'Containers' feature is the documented one; 'HypervisorPlatform' is the
    # cross-edition fallback (available on Win11 Home, unlike Containers).
    _NETNAT_FEATURES = ("Containers", "HypervisorPlatform")

    def check_prerequisites(self) -> PrerequisiteResult:
        if self._netnat_class_available():
            return PrerequisiteResult(status=PrerequisiteStatus.OK)

        log.info(
            "MSFT_NetNat WMI class not registered — attempting to enable "
            "Windows optional features that ship it"
        )
        needs_reboot = False
        for feature in self._NETNAT_FEATURES:
            outcome = self._enable_feature(feature)
            if outcome == "reboot":
                log.info("Feature '%s' enabled but reboot is required", feature)
                needs_reboot = True
                break
            # Enabled in-place — re-probe; if the class is live, we're done.
            # Otherwise try the next feature before giving up.
            if outcome == "enabled" and self._netnat_class_available():
                log.info("MSFT_NetNat registered after enabling '%s'", feature)
                return PrerequisiteResult(status=PrerequisiteStatus.OK)

        if needs_reboot:
            return PrerequisiteResult(
                status=PrerequisiteStatus.REBOOT_REQUIRED,
                detail=(
                    "The 'Containers' Windows feature was enabled but Windows "
                    "needs a reboot before the NAT driver becomes available."
                ),
                remediation=(
                    "Reboot Windows and re-run OutWarp Server setup. "
                    "The reboot is mandatory even if a previous DISM run "
                    "reported 'RestartNeeded: False'."
                ),
            )

        return PrerequisiteResult(
            status=PrerequisiteStatus.FAILED,
            detail=(
                "The MSFT_NetNat WMI provider is not available and could not be "
                "auto-installed. Without it the server cannot NAT client traffic "
                "to the internet — clients would connect but get no data back."
            ),
            remediation=(
                "Possible causes and fixes:\n"
                "  1. Reboot and re-run setup (some Windows builds report "
                "'RestartNeeded: False' but still need one).\n"
                "  2. Repair the Windows image: as admin, run "
                "'DISM /Online /Cleanup-Image /RestoreHealth' then 'sfc /scannow' "
                "and reboot.\n"
                "  3. Check Microsoft Defender history for quarantined NetNat.dll "
                "or NetNat.mof (under C:\\Windows\\System32\\wbem\\) and restore them.\n"
                "  4. As a fallback, deploy OutWarp Server on Linux — iptables "
                "MASQUERADE works out of the box with no driver dance."
            ),
        )

    def _netnat_class_available(self) -> bool:
        """Whether MSFT_NetNat is registered in the WMI repository.

        We probe with a literal-string echo instead of relying on exit codes so
        a non-zero return (PSv5 quirk on some hosts) does not produce a false
        negative.
        """
        r = _ps(
            "if (Get-CimClass -ClassName MSFT_NetNat "
            "-Namespace ROOT/StandardCimv2 -ErrorAction SilentlyContinue) "
            "{ 'OK' } else { 'MISSING' }"
        )
        return "OK" in (r.stdout or "")

    def _enable_feature(self, feature: str) -> str:
        """Attempt to enable a Windows optional feature.

        Returns one of: 'enabled' (online now), 'reboot' (needs restart), or
        'failed'. We swallow all errors and turn them into 'failed' — callers
        try the next candidate feature so a single missing one (e.g. Containers
        on Home) doesn't block the whole prerequisite check.
        """
        result = _ps(
            f"$r = Enable-WindowsOptionalFeature -Online -FeatureName {feature} "
            "-All -NoRestart -ErrorAction SilentlyContinue; "
            "if ($null -eq $r) { 'failed' } "
            "elseif ($r.RestartNeeded) { 'reboot' } "
            "else { 'enabled' }"
        )
        out = (result.stdout or "").strip().lower()
        if "reboot" in out:
            return "reboot"
        if "enabled" in out:
            return "enabled"
        detail = (result.stderr or "").strip() or out
        log.warning("Enable-WindowsOptionalFeature %s: %s", feature, detail)
        return "failed"

    def _enable_ip_forwarding(self) -> None:
        try:
            import winreg
            key_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, key_path, access=winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "IPEnableRouter", 0, winreg.REG_DWORD, 1)
            log.info("IP routing enabled via registry")
        except OSError as exc:
            log.warning("Could not enable IP routing in registry: %s", exc)
        # Also activate immediately without requiring a reboot.
        result = _ps("Get-NetIPInterface | Set-NetIPInterface -Forwarding Enabled")
        if result.returncode != 0:
            log.warning(
                "Could not enable forwarding via Set-NetIPInterface: %s", result.stderr.strip(),
            )

    def _create_nat(self, subnet: str) -> None:
        check = _ps(
            f"Get-NetNat -Name '{_NAT_NAME}' -ErrorAction SilentlyContinue "
            "| Select-Object -ExpandProperty Name"
        )
        if _NAT_NAME in check.stdout:
            log.debug("NetNat '%s' already exists", _NAT_NAME)
            return
        result = _ps(
            f"New-NetNat -Name '{_NAT_NAME}' -InternalIPInterfaceAddressPrefix '{subnet}'"
        )
        if result.returncode == 0:
            log.info("Created NetNat '%s' for subnet %s", _NAT_NAME, subnet)
            return

        # Used to be a silent log.warning here. The result was a server that
        # appeared healthy (wstunnel listening, WG handshakes completing) but
        # produced no return traffic — clients connected and lost internet.
        # Raise instead so callers (server_manager._do_start, the setup wizard)
        # surface the failure in the GUI.
        err = (result.stderr or result.stdout or "").strip()
        if any(s in err for s in ("Invalid class", "Clase no válida", "0x80041010")):
            raise PlatformError(
                "Could not create NetNat: the MSFT_NetNat WMI provider is not "
                "registered. Enable the 'Containers' Windows feature, reboot, "
                "and re-run setup. (Underlying error: " + err + ")"
            )
        raise PlatformError(
            f"Could not create NetNat for {subnet}: {err}"
        )

    def _remove_nat(self) -> None:
        _ps(f"Remove-NetNat -Name '{_NAT_NAME}' -Confirm:$false -ErrorAction SilentlyContinue")

    def _add_firewall_rule(self, port: int) -> None:
        _run(
            "netsh", "advfirewall", "firewall", "add", "rule",
            "name=OutWarp-wstunnel", "dir=in", "action=allow",
            f"localport={port}", "protocol=TCP",
            check=False,
        )
        log.info("Firewall rule added for port %d/tcp", port)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require_wireguard(self) -> None:
        if not _WG_EXE.exists():
            raise PlatformError(
                f"WireGuard for Windows not found at {_WG_EXE}. "
                "Install it from https://www.wireguard.com/install/ and retry."
            )

    def _wait_service_running(self, interface: str, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "RUNNING" in _run("sc", "query", f"WireGuardTunnel${interface}", check=False).stdout:
                return
            time.sleep(0.25)
        log.warning("WireGuard '%s' did not reach RUNNING within %.0fs", interface, timeout)

    def _wait_service_gone(self, interface: str, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _run("sc", "query", f"WireGuardTunnel${interface}", check=False).returncode != 0:
                return
            time.sleep(0.25)
