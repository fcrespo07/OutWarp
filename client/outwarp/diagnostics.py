"""Client-side health checks for `outwarp-cli doctor` and the TUI doctor screen."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


FixKind = Literal["auto", "interactive", "manual"]


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    remediation: str | None = None
    remediation_command: str | None = None
    fix_kind: FixKind | None = None
    fix_callable: Callable[[], None] | None = field(default=None, repr=False)


@dataclass
class Check:
    key: str
    category: str
    runner: Callable[[], CheckResult]


_DEFAULT_HELPER = Path("/usr/local/libexec/outwarp-priv")
_WSTUNNEL_VERSION_FILE = Path(__file__).parent.parent.parent / "installer" / "wstunnel-version.txt"


def _run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout,
    )


def check_wstunnel_binary() -> CheckResult:
    """wstunnel must be on PATH or in a known location."""
    wstunnel = shutil.which("wstunnel")
    if not wstunnel:
        # Check common install location
        candidate = Path("/usr/local/bin/wstunnel")
        if candidate.exists():
            wstunnel = str(candidate)
    if not wstunnel:
        return CheckResult(
            name="wstunnel binary",
            status=Status.FAIL,
            detail="wstunnel not found on PATH.",
            remediation=(
                "Reinstall OutWarp: bash <(curl -fsSL https://outwarp.dev/install.sh) client"
            ),
            remediation_command="bash <(curl -fsSL https://outwarp.dev/install.sh) client",
            fix_kind="manual",
        )
    try:
        proc = _run([wstunnel, "--version"])
        version = (proc.stdout or proc.stderr or "").strip().split("\n")[0]
    except Exception as exc:
        return CheckResult(
            name="wstunnel binary",
            status=Status.WARN,
            detail=f"Found at {wstunnel} but version check failed: {exc}",
        )
    return CheckResult(
        name="wstunnel binary",
        status=Status.PASS,
        detail=f"{wstunnel} ({version})",
    )


def check_wstunnel_version_pin() -> CheckResult:
    """wstunnel version should match the pinned version in the installer."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="wstunnel version pin",
            status=Status.SKIP,
            detail="Version pin check is Linux-only.",
        )
    try:
        pin_path = _WSTUNNEL_VERSION_FILE
        if not pin_path.exists():
            # Try relative to the installed package location
            pin_path = (
                Path(__file__).parent.parent.parent.parent / "installer" / "wstunnel-version.txt"
            )
        if not pin_path.exists():
            return CheckResult(
                name="wstunnel version pin",
                status=Status.SKIP,
                detail="wstunnel-version.txt not found — skipping pin check.",
            )
        pinned = pin_path.read_text(encoding="utf-8").strip()
    except OSError:
        return CheckResult(
            name="wstunnel version pin",
            status=Status.SKIP,
            detail="Cannot read version pin file.",
        )
    wstunnel = shutil.which("wstunnel")
    if not wstunnel:
        return CheckResult(
            name="wstunnel version pin",
            status=Status.FAIL,
            detail=f"wstunnel not found; pinned version is {pinned}.",
        )
    try:
        proc = _run([wstunnel, "--version"])
        raw = (proc.stdout or proc.stderr or "").strip()
        # wstunnel outputs "wstunnel X.Y.Z" or just "X.Y.Z"
        version = raw.split()[-1] if raw else "?"
    except Exception:
        version = "?"
    if version == pinned:
        return CheckResult(
            name="wstunnel version pin",
            status=Status.PASS,
            detail=f"{version} matches pin",
        )
    return CheckResult(
        name="wstunnel version pin",
        status=Status.WARN,
        detail=f"installed={version}, pinned={pinned} — version mismatch may cause HTTP 400.",
        remediation=(
            f"Reinstall the exact version: download wstunnel {pinned} from GitHub and replace."
        ),
        fix_kind="manual",
    )


def check_helper_installed() -> CheckResult:
    """The privileged helper at /usr/local/libexec/outwarp-priv must exist on Linux."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="privileged helper",
            status=Status.SKIP,
            detail="Linux-only.",
        )
    helper = Path(os.environ.get("OUTWARP_HELPER") or str(_DEFAULT_HELPER))
    if helper.exists():
        return CheckResult(
            name="privileged helper",
            status=Status.PASS,
            detail=str(helper),
        )
    return CheckResult(
        name="privileged helper",
        status=Status.FAIL,
        detail=f"{helper} not found — wg stats and WireGuard operations will fail.",
        remediation=(
            "Re-run the installer: bash <(curl -fsSL https://outwarp.dev/install.sh) client"
        ),
        remediation_command="bash <(curl -fsSL https://outwarp.dev/install.sh) client",
        fix_kind="manual",
    )


def check_sudoers() -> CheckResult:
    """The helper's sudoers rule must allow passwordless execution."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="sudoers rule",
            status=Status.SKIP,
            detail="Linux-only.",
        )
    helper = Path(os.environ.get("OUTWARP_HELPER") or str(_DEFAULT_HELPER))
    if not helper.exists():
        return CheckResult(
            name="sudoers rule",
            status=Status.SKIP,
            detail="Helper not found — skipping sudoers check.",
        )
    try:
        proc = _run(["sudo", "-n", str(helper), "version"], timeout=3)
        if proc.returncode == 0:
            return CheckResult(
                name="sudoers rule",
                status=Status.PASS,
                detail="sudo -n works for the helper",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return CheckResult(
        name="sudoers rule",
        status=Status.FAIL,
        detail="sudo -n outwarp-priv failed — passwordless sudo not configured.",
        remediation=(
            f"Add to /etc/sudoers.d/outwarp: "
            f"ALL ALL=(root) NOPASSWD: {helper}"
        ),
        remediation_command=(
            f"echo 'ALL ALL=(root) NOPASSWD: {helper}' "
            f"| sudo tee /etc/sudoers.d/outwarp"
        ),
        fix_kind="interactive",
    )


def check_wireguard_tools() -> CheckResult:
    """wg-quick and wg must be available."""
    if sys.platform == "win32":
        wg_path = Path(r"C:\Program Files\WireGuard\wg.exe")
        wgq_path = Path(r"C:\Program Files\WireGuard\wg-quick.exe")
        if wg_path.exists() and wgq_path.exists():
            return CheckResult(
                name="WireGuard tools",
                status=Status.PASS,
                detail="WireGuard for Windows installed",
            )
        return CheckResult(
            name="WireGuard tools",
            status=Status.FAIL,
            detail="WireGuard for Windows not found at default path.",
            remediation="Install from https://www.wireguard.com/install/",
            fix_kind="manual",
        )
    wg = shutil.which("wg")
    wgq = shutil.which("wg-quick")
    if wg and wgq:
        try:
            version = _run([wg, "--version"]).stdout.strip()
        except Exception:
            version = wg
        return CheckResult(
            name="WireGuard tools",
            status=Status.PASS,
            detail=version or wg,
        )
    missing = [t for t in ("wg", "wg-quick") if not shutil.which(t)]
    pm_cmd = _wg_install_cmd()
    return CheckResult(
        name="WireGuard tools",
        status=Status.FAIL,
        detail=f"Missing: {', '.join(missing)}",
        remediation=f"Install wireguard-tools: {pm_cmd}",
        remediation_command=pm_cmd,
        fix_kind="interactive",
    )


def _wg_install_cmd() -> str:
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


def check_wg_kernel_module() -> CheckResult:
    """WireGuard kernel module must be loadable (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="WireGuard kernel module",
            status=Status.SKIP,
            detail="Linux-only.",
        )
    proc = _run(["modinfo", "wireguard"])
    if proc.returncode == 0:
        first = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("filename:")),
            "available",
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
        remediation="Install wireguard kernel module: apt install wireguard",
        remediation_command="apt install wireguard",
        fix_kind="interactive",
    )


def check_systemd_unit() -> CheckResult:
    """The outwarp-client systemd user unit state (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="systemd user unit",
            status=Status.SKIP,
            detail="Linux-only.",
        )
    proc = _run(["systemctl", "--user", "is-enabled", "outwarp-client.service"])
    enabled = proc.stdout.strip()
    proc2 = _run(["systemctl", "--user", "is-active", "outwarp-client.service"])
    active = proc2.stdout.strip()
    if enabled == "enabled" and active == "active":
        return CheckResult(
            name="systemd user unit",
            status=Status.PASS,
            detail="outwarp-client.service enabled + active",
        )
    if enabled == "enabled" and active != "active":
        return CheckResult(
            name="systemd user unit",
            status=Status.WARN,
            detail=f"enabled but active={active}",
            remediation="Start with: systemctl --user start outwarp-client.service",
            remediation_command="systemctl --user start outwarp-client.service",
            fix_kind="auto",
            fix_callable=lambda: subprocess.run(
                ["systemctl", "--user", "start", "outwarp-client.service"],
                check=True, capture_output=True, text=True,
            ),
        )
    if enabled in ("disabled", "static", "masked"):
        return CheckResult(
            name="systemd user unit",
            status=Status.WARN,
            detail=f"status={enabled} — background daemon won't autostart.",
            remediation="Enable with: outwarp-cli service install",
            remediation_command="outwarp-cli service install",
            fix_kind="manual",
        )
    # Not installed (not-found)
    return CheckResult(
        name="systemd user unit",
        status=Status.WARN,
        detail="outwarp-client.service not installed.",
        remediation="Install with: outwarp-cli service install",
        remediation_command="outwarp-cli service install",
        fix_kind="manual",
    )


def check_notify_send() -> CheckResult:
    """notify-send should be available for desktop notifications (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name="notify-send",
            status=Status.SKIP,
            detail="Linux-only.",
        )
    if shutil.which("notify-send"):
        return CheckResult(
            name="notify-send",
            status=Status.PASS,
            detail="notify-send on PATH",
        )
    return CheckResult(
        name="notify-send",
        status=Status.WARN,
        detail="notify-send not found — desktop notifications will be silent.",
        remediation="Install libnotify-bin: apt install libnotify-bin",
        remediation_command="apt install libnotify-bin",
        fix_kind="interactive",
    )


def check_config_present() -> CheckResult:
    """The imported .owcfg must exist as config.json."""
    from outwarp.config import default_config_path
    path = default_config_path()
    if path.exists():
        return CheckResult(
            name="Profile imported",
            status=Status.PASS,
            detail=str(path),
        )
    return CheckResult(
        name="Profile imported",
        status=Status.FAIL,
        detail="No profile found — run 'outwarp-cli import <path.owcfg>'.",
        remediation="outwarp-cli import <path-to.owcfg>",
        remediation_command="outwarp-cli import <path-to.owcfg>",
        fix_kind="manual",
    )


def gather_checks() -> list[Check]:
    checks = [
        Check("config", "Config", check_config_present),
        Check("wstunnel", "Binaries", check_wstunnel_binary),
        Check("wstunnel_pin", "Binaries", check_wstunnel_version_pin),
        Check("wg_tools", "Binaries", check_wireguard_tools),
    ]
    if sys.platform.startswith("linux"):
        checks += [
            Check("helper", "Permissions", check_helper_installed),
            Check("sudoers", "Permissions", check_sudoers),
            Check("kmod", "WireGuard", check_wg_kernel_module),
            Check("systemd", "Service", check_systemd_unit),
            Check("notify", "Desktop", check_notify_send),
        ]
    return checks


def run_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in gather_checks():
        try:
            results.append(check.runner())
        except Exception as exc:
            log.exception("Client diagnostics check %r raised", check.key)
            results.append(
                CheckResult(
                    name=check.key,
                    status=Status.FAIL,
                    detail=f"Check crashed: {exc}",
                )
            )
    return results
