"""Client-side health checks for `outwarp doctor` and the TUI doctor screen."""
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

from outwarp.i18n import t

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


_INSTALL_CMD = "bash <(curl -fsSL https://outwarp.dev/install.sh) client"
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
            name=t("dx.name.wstunnel"),
            status=Status.FAIL,
            detail=t("dx.wstunnel.missing"),
            remediation=t("dx.reinstall", cmd=_INSTALL_CMD),
            remediation_command=_INSTALL_CMD,
            fix_kind="manual",
        )
    try:
        proc = _run([wstunnel, "--version"])
        version = (proc.stdout or proc.stderr or "").strip().split("\n")[0]
    except Exception as exc:
        return CheckResult(
            name=t("dx.name.wstunnel"),
            status=Status.WARN,
            detail=t("dx.wstunnel.version_failed", path=wstunnel, error=exc),
        )
    return CheckResult(
        name=t("dx.name.wstunnel"),
        status=Status.PASS,
        detail=f"{wstunnel} ({version})",
    )


def check_wstunnel_version_pin() -> CheckResult:
    """wstunnel version should match the pinned version in the installer."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.wstunnel_pin"),
            status=Status.SKIP,
            detail=t("dx.pin.linux_only"),
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
                name=t("dx.name.wstunnel_pin"),
                status=Status.SKIP,
                detail=t("dx.pin.no_file"),
            )
        pinned = pin_path.read_text(encoding="utf-8").strip()
    except OSError:
        return CheckResult(
            name=t("dx.name.wstunnel_pin"),
            status=Status.SKIP,
            detail=t("dx.pin.unreadable"),
        )
    wstunnel = shutil.which("wstunnel")
    if not wstunnel:
        return CheckResult(
            name=t("dx.name.wstunnel_pin"),
            status=Status.FAIL,
            detail=t("dx.pin.not_found", pinned=pinned),
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
            name=t("dx.name.wstunnel_pin"),
            status=Status.PASS,
            detail=t("dx.pin.matches", version=version),
        )
    return CheckResult(
        name=t("dx.name.wstunnel_pin"),
        status=Status.WARN,
        detail=t("dx.pin.mismatch", version=version, pinned=pinned),
        remediation=t("dx.pin.mismatch_fix", pinned=pinned),
        fix_kind="manual",
    )


def check_helper_installed() -> CheckResult:
    """The privileged helper at /usr/local/libexec/outwarp-priv must exist on Linux."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.helper"),
            status=Status.SKIP,
            detail=t("dx.linux_only"),
        )
    helper = Path(os.environ.get("OUTWARP_HELPER") or str(_DEFAULT_HELPER))
    if helper.exists():
        return CheckResult(
            name=t("dx.name.helper"),
            status=Status.PASS,
            detail=str(helper),
        )
    return CheckResult(
        name=t("dx.name.helper"),
        status=Status.FAIL,
        detail=t("dx.helper.missing", path=helper),
        remediation=t("dx.rerun_installer", cmd=_INSTALL_CMD),
        remediation_command=_INSTALL_CMD,
        fix_kind="manual",
    )


# Helper contract version this client was built against (install.sh
# HELPER_VERSION). 2 = kill switch takes the tunnel interface + CIDRs.
EXPECTED_HELPER_VERSION = 2


def check_helper_version() -> CheckResult:
    """The installed helper must speak the contract this client expects.

    Wheel upgrades (`outwarp update`, pipx) don't touch the helper, so a
    client can outrun it; the kill switch then fails to engage (fail-open).
    """
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.helper_version"), status=Status.SKIP, detail=t("dx.linux_only"),
        )
    helper = Path(os.environ.get("OUTWARP_HELPER") or str(_DEFAULT_HELPER))
    if not helper.exists():
        return CheckResult(
            name=t("dx.name.helper_version"), status=Status.SKIP,
            detail=t("dx.helper.skip_version"),
        )
    installed: int | None = None
    try:
        proc = _run(["sudo", "-n", str(helper), "version"], timeout=3)
        if proc.returncode == 0 and proc.stdout.strip().isdigit():
            installed = int(proc.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if installed is not None and installed >= EXPECTED_HELPER_VERSION:
        return CheckResult(
            name=t("dx.name.helper_version"), status=Status.PASS,
            detail=t("dx.helper.version_ok", version=installed),
        )
    found = t("dx.helper.pre012") if installed is None else f"v{installed}"
    return CheckResult(
        name=t("dx.name.helper_version"),
        status=Status.WARN,
        detail=t("dx.helper.outdated", found=found, expected=EXPECTED_HELPER_VERSION),
        remediation=t("dx.helper.refresh"),
        remediation_command=_INSTALL_CMD,
        fix_kind="manual",
    )


def check_sudoers() -> CheckResult:
    """The helper's sudoers rule must allow passwordless execution."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.sudoers"),
            status=Status.SKIP,
            detail=t("dx.linux_only"),
        )
    helper = Path(os.environ.get("OUTWARP_HELPER") or str(_DEFAULT_HELPER))
    if not helper.exists():
        return CheckResult(
            name=t("dx.name.sudoers"),
            status=Status.SKIP,
            detail=t("dx.sudoers.skip"),
        )
    # `sudo -l <cmd>` exits 0 only when the rule allows it without a password;
    # it never runs the helper (which has no `version` subcommand — checking
    # by running one reported every Linux install as misconfigured).
    try:
        proc = _run(["sudo", "-n", "-l", str(helper)], timeout=3)
        if proc.returncode == 0:
            return CheckResult(
                name=t("dx.name.sudoers"),
                status=Status.PASS,
                detail=t("dx.sudoers.ok"),
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return CheckResult(
        name=t("dx.name.sudoers"),
        status=Status.FAIL,
        detail=t("dx.sudoers.failed"),
        remediation=t("dx.sudoers.fix", rule=f"ALL ALL=(root) NOPASSWD: {helper}"),
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
                name=t("dx.name.wg_tools"),
                status=Status.PASS,
                detail=t("dx.wg.windows_ok"),
            )
        return CheckResult(
            name=t("dx.name.wg_tools"),
            status=Status.FAIL,
            detail=t("dx.wg.windows_missing"),
            remediation=t("dx.wg.install_from", url="https://www.wireguard.com/install/"),
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
            name=t("dx.name.wg_tools"),
            status=Status.PASS,
            detail=version or wg,
        )
    missing = [tool for tool in ("wg", "wg-quick") if not shutil.which(tool)]
    pm_cmd = _wg_install_cmd()
    return CheckResult(
        name=t("dx.name.wg_tools"),
        status=Status.FAIL,
        detail=t("dx.wg.missing", tools=", ".join(missing)),
        remediation=t("dx.wg.install_tools", cmd=pm_cmd),
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
    return t("dx.pm.wireguard")


def check_nftables() -> CheckResult:
    """The kill switch is an nftables table the helper manages — no `nft`,
    no switch (it used to fail only when the user flipped the toggle)."""
    if shutil.which("nft"):
        return CheckResult(name=t("dx.name.nftables"), status=Status.PASS, detail=t("dx.nft.ok"))
    pm = _wg_install_cmd().replace("wireguard-tools", "nftables")
    return CheckResult(
        name=t("dx.name.nftables"),
        status=Status.WARN,
        detail=t("dx.nft.missing"),
        remediation=t("dx.nft.install", cmd=pm),
        remediation_command=pm,
        fix_kind="interactive",
    )


def check_wg_kernel_module() -> CheckResult:
    """WireGuard kernel module must be loadable (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.kmod"),
            status=Status.SKIP,
            detail=t("dx.linux_only"),
        )
    proc = _run(["modinfo", "wireguard"])
    if proc.returncode == 0:
        first = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("filename:")),
            "available",
        )
        return CheckResult(
            name=t("dx.name.kmod"),
            status=Status.PASS,
            detail=first,
        )
    return CheckResult(
        name=t("dx.name.kmod"),
        status=Status.FAIL,
        detail=t("dx.kmod.missing"),
        remediation=t("dx.kmod.install", cmd="apt install wireguard"),
        remediation_command="apt install wireguard",
        fix_kind="interactive",
    )


def check_systemd_unit() -> CheckResult:
    """The outwarp-client systemd user unit state (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.systemd"),
            status=Status.SKIP,
            detail=t("dx.linux_only"),
        )
    proc = _run(["systemctl", "--user", "is-enabled", "outwarp-client.service"])
    enabled = proc.stdout.strip()
    proc2 = _run(["systemctl", "--user", "is-active", "outwarp-client.service"])
    active = proc2.stdout.strip()
    if enabled == "enabled" and active == "active":
        return CheckResult(
            name=t("dx.name.systemd"),
            status=Status.PASS,
            detail=t("dx.unit.ok"),
        )
    if enabled == "enabled" and active != "active":
        return CheckResult(
            name=t("dx.name.systemd"),
            status=Status.WARN,
            detail=t("dx.unit.not_active", active=active),
            remediation=t("dx.unit.start", cmd="systemctl --user start outwarp-client.service"),
            remediation_command="systemctl --user start outwarp-client.service",
            fix_kind="auto",
            fix_callable=lambda: subprocess.run(
                ["systemctl", "--user", "start", "outwarp-client.service"],
                check=True, capture_output=True, text=True,
            ),
        )
    if enabled in ("disabled", "static", "masked"):
        return CheckResult(
            name=t("dx.name.systemd"),
            status=Status.WARN,
            detail=t("dx.unit.disabled", status=enabled),
            remediation=t("dx.unit.enable", cmd="outwarp service install"),
            remediation_command="outwarp service install",
            fix_kind="manual",
        )
    # Not installed (not-found)
    return CheckResult(
        name=t("dx.name.systemd"),
        status=Status.WARN,
        detail=t("dx.unit.missing"),
        remediation=t("dx.unit.install", cmd="outwarp service install"),
        remediation_command="outwarp service install",
        fix_kind="manual",
    )


def check_notify_send() -> CheckResult:
    """notify-send should be available for desktop notifications (Linux only)."""
    if not sys.platform.startswith("linux"):
        return CheckResult(
            name=t("dx.name.notify"),
            status=Status.SKIP,
            detail=t("dx.linux_only"),
        )
    if shutil.which("notify-send"):
        return CheckResult(
            name=t("dx.name.notify"),
            status=Status.PASS,
            detail=t("dx.notify.ok"),
        )
    pkg = _notify_pkg_cmd()
    return CheckResult(
        name=t("dx.name.notify"),
        status=Status.WARN,
        detail=t("dx.notify.missing"),
        remediation=t("dx.notify.install", cmd=pkg),
        remediation_command=pkg,
        fix_kind="interactive",
    )


def _notify_pkg_cmd() -> str:
    if shutil.which("apt"):
        return "apt install libnotify-bin"
    if shutil.which("dnf"):
        return "dnf install libnotify"
    if shutil.which("pacman"):
        return "pacman -S libnotify"
    if shutil.which("zypper"):
        return "zypper install libnotify-tools"
    return t("dx.pm.libnotify")


def check_tray_backend() -> CheckResult:
    """Will the tray icon show up in this session's bar?

    Verified on Omarchy: pystray's appindicator backend registers a
    StatusNotifierItem with omarchy-shell's watcher and the icon follows the
    tunnel state — but only when the GObject bindings are importable from
    the venv. Without them pystray falls back to Xorg and nothing appears
    under Wayland."""
    from outwarp.desktop_linux import tray_status

    state, detail = tray_status()
    if state == "skip":
        return CheckResult(name=t("dx.name.tray"), status=Status.SKIP, detail=detail)
    if state == "ok":
        return CheckResult(name=t("dx.name.tray"), status=Status.PASS, detail=detail)
    return CheckResult(
        name=t("dx.name.tray"),
        status=Status.WARN,
        detail=detail,
        remediation=t("dx.tray.fix"),
        remediation_command="sudo outwarp gui --install",
        fix_kind="interactive",
    )


def check_hyprland_rule() -> CheckResult:
    """Hyprland tiles the OutWarp window unless a rule floats it."""
    from outwarp.desktop_linux import (
        hyprland_config_kind,
        hyprland_rule_installed,
        hyprland_rule_snippet,
        is_hyprland,
    )

    if not is_hyprland():
        return CheckResult(name=t("dx.name.hyprland"), status=Status.SKIP, detail=t("dx.hypr.not"))
    if hyprland_config_kind() is None:
        return CheckResult(name=t("dx.name.hyprland"), status=Status.WARN,
                           detail=t("dx.hypr.no_config"))
    if hyprland_rule_installed():
        return CheckResult(name=t("dx.name.hyprland"), status=Status.PASS,
                           detail=t("dx.hypr.ok"))
    return CheckResult(
        name=t("dx.name.hyprland"),
        status=Status.WARN,
        detail=t("dx.hypr.missing"),
        remediation=t("dx.hypr.fix") + "\n" + hyprland_rule_snippet().rstrip(),
        remediation_command="outwarp ui --hyprland-rule",
        fix_kind="auto",
    )


def check_config_present() -> CheckResult:
    """The imported .owcfg must exist as config.json."""
    from outwarp.config import default_config_path
    path = default_config_path()
    if path.exists():
        return CheckResult(
            name=t("dx.name.profile"),
            status=Status.PASS,
            detail=str(path),
        )
    return CheckResult(
        name=t("dx.name.profile"),
        status=Status.FAIL,
        detail=t("dx.config.missing"),
        remediation="outwarp import <path-to.owcfg>",
        remediation_command="outwarp import <path-to.owcfg>",
        fix_kind="manual",
    )


def _which_all(name: str) -> list[Path]:
    """Every ``name`` on PATH, first match first (``which -a``), deduplicated
    by resolved target so two symlinks to one venv count once."""
    seen: set[Path] = set()
    out: list[Path] = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / name
        if cand.is_file() and os.access(cand, os.X_OK):
            real = cand.resolve()
            if real not in seen:
                seen.add(real)
                out.append(cand)
    return out


def _binary_version(path: Path) -> str:
    try:
        proc = _run([str(path), "--version"])
    except (OSError, subprocess.TimeoutExpired):
        return "?"
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[-1].split()[-1] if text else "?"


def check_duplicate_binaries() -> CheckResult:
    """More than one `outwarp` on PATH is how a stale venv keeps answering.

    Seen on the author's laptop: install.sh's /opt/pipx venv at 0.5.8 and a
    user pipx venv at 0.13.0 both exposed as `outwarp-cli`; which one a shell
    or a unit picked depended on PATH order."""
    found = [(p, _binary_version(p)) for p in _which_all("outwarp")]
    seen = {p.resolve() for p, _ in found}
    found += [(p, _binary_version(p)) for p in _which_all("outwarp-cli")
              if p.resolve() not in seen]
    if not found:
        return CheckResult(
            name=t("dx.name.binaries"),
            status=Status.WARN,
            detail=t("dx.bin.none"),
        )
    versions = {v for _, v in found}
    listing = ", ".join(f"{p} ({v})" for p, v in found)
    if len(found) > 1 and len(versions) > 1:
        return CheckResult(
            name=t("dx.name.binaries"),
            status=Status.WARN,
            detail=t("dx.bin.several", listing=listing),
            remediation=t("dx.bin.fix"),
        )
    return CheckResult(name=t("dx.name.binaries"), status=Status.PASS, detail=listing)


_LEGACY_NAME_FILES: tuple[tuple[str, Path], ...] = (
    ("dx.legacy.bash", Path("/etc/bash_completion.d/outwarp-cli")),
    ("dx.legacy.zsh", Path("/usr/share/zsh/site-functions/_outwarp-cli")),
)
_SYSTEM_LAUNCHER = Path("/usr/share/applications/outwarp.desktop")


def check_legacy_cli_name() -> CheckResult:
    """Anything on disk still wired to the pre-1.0 `outwarp-cli` name.

    The alias keeps those working for one release; this is the nudge to
    migrate before it disappears."""
    from outwarp.service import unit_uses_legacy_name

    stale: list[str] = []
    if unit_uses_legacy_name():
        stale.append(t("dx.legacy.unit"))
    try:
        if "outwarp-cli" in _SYSTEM_LAUNCHER.read_text():
            stale.append(t("dx.legacy.launcher", path=_SYSTEM_LAUNCHER))
    except OSError:
        pass
    stale += [f"{t(label)} {path}" for label, path in _LEGACY_NAME_FILES if path.exists()]
    if not stale:
        return CheckResult(
            name=t("dx.name.cli_name"), status=Status.PASS,
            detail=t("dx.legacy.none"),
        )
    return CheckResult(
        name=t("dx.name.cli_name"),
        status=Status.WARN,
        detail=t("dx.legacy.found", items="; ".join(stale)),
        remediation=t("dx.legacy.fix"),
        remediation_command="outwarp service install",
    )


def check_gui_stack() -> CheckResult:
    """Can `outwarp gui` open here? Linux ships the window as an optional
    stack; on a headless box its absence is expected, not a problem."""
    from outwarp.ui_choice import INSTALL_HINT, desktop_session, gui_available, preferred_ui

    ok, why = gui_available()
    pref = preferred_ui()
    if ok:
        return CheckResult(name=t("dx.name.gui"), status=Status.PASS,
                           detail=t("dx.gui.ok", why=why, pref=pref))
    if not desktop_session() and pref != "gui":
        return CheckResult(name=t("dx.name.gui"), status=Status.SKIP,
                           detail=t("dx.gui.headless", why=why))
    return CheckResult(
        name=t("dx.name.gui"),
        status=Status.WARN,
        detail=t("dx.gui.missing", why=why),
        remediation=t("dx.gui.fix", hint=INSTALL_HINT),
        remediation_command=INSTALL_HINT,
        fix_kind="interactive",
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
            Check("helper_version", "Permissions", check_helper_version),
            Check("kmod", "WireGuard", check_wg_kernel_module),
            Check("nftables", "WireGuard", check_nftables),
            Check("systemd", "Service", check_systemd_unit),
            Check("notify", "Desktop", check_notify_send),
            Check("gui", "Desktop", check_gui_stack),
            Check("tray", "Desktop", check_tray_backend),
            Check("hyprland", "Desktop", check_hyprland_rule),
            Check("binaries", "Install", check_duplicate_binaries),
            Check("cli_name", "Install", check_legacy_cli_name),
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
                    detail=t("dx.crashed", error=exc),
                )
            )
    return results
