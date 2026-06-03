"""outwarp-cli uninstall — purges every artifact installed by install.ps1 / install.sh.

Layout we need to clean on Linux (handles both the 0.4.x legacy and the 0.5.x
pipx-managed install, since users may upgrade in place):

  Legacy (≤ 0.4.x)
    /opt/outwarp-client/             venv prefix
    /usr/local/bin/outwarp           tray launcher
    /usr/local/bin/outwarp-cli       headless CLI
    /usr/local/bin/outwarp-uninstall the standalone uninstaller binary

  Pipx (≥ 0.5.0)
    /opt/pipx/venvs/outwarp-client/  pipx-managed venv
    /usr/local/bin/outwarp-cli       single entry-point

  Shared
    /usr/local/libexec/outwarp-priv  privileged helper (added in 0.5.0)
    /etc/sudoers.d/outwarp           NOPASSWD rule for the helper
    ~/.config/autostart/outwarp.desktop  legacy XDG autostart (0.4.x → removed)

Windows still uses %ProgramFiles%\\OutWarp\\client + %ProgramFiles%\\OutWarp\\outwarp.bat.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _require_admin() -> None:
    if sys.platform == "win32":
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("Error: run this command from an elevated (Administrator) prompt.")
            print("  Right-click PowerShell → 'Run as administrator', then:")
            print("  outwarp-cli uninstall")
            raise SystemExit(1)
    else:
        if os.geteuid() != 0:
            print("Error: run with sudo.")
            print("  sudo outwarp-cli uninstall")
            raise SystemExit(1)


def _confirm(yes: bool) -> None:
    print()
    print("This will permanently remove:")
    for line in _what_gets_removed():
        print(f"  • {line}")
    print()
    if yes:
        return
    answer = input("Type 'yes' to confirm: ").strip().lower()
    if answer != "yes":
        print("Aborted.")
        raise SystemExit(0)
    print()


def _what_gets_removed() -> list[str]:
    items: list[str] = []
    for prefix in _client_prefixes():
        items.append(f"Install directory: {prefix}")
    for shim in _client_shims():
        items.append(f"Binary: {shim}")
    for path in _extra_artifacts():
        items.append(f"File: {path}")
    config = _config_dir()
    startup = _startup_shortcut()
    desktop = _desktop_shortcut()
    if config and config.exists():
        items.append(f"Config and logs: {config}")
    if startup and startup.exists():
        items.append(f"Startup shortcut: {startup}")
    if desktop and desktop.exists():
        items.append(f"Desktop shortcut: {desktop}")
    if not items:
        items.append("(nothing detected — already uninstalled?)")
    return items


# ---------------------------------------------------------------------------
# Path detection — mirrors what install.ps1 / install.sh write
# ---------------------------------------------------------------------------

def _client_prefixes() -> list[Path]:
    """Every install prefix we have to wipe. A normal machine has exactly
    one; in-place upgrades from 0.4.x → 0.5.x can briefly have both."""
    if sys.platform == "win32":
        prog = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        p = Path(prog) / "OutWarp" / "client"
        return [p] if p.exists() else []
    if sys.platform == "linux":
        candidates = [
            Path("/opt/pipx/venvs/outwarp-client"),
            Path("/opt/outwarp-client"),
        ]
        return [p for p in candidates if p.exists()]
    return []


def _client_shims() -> list[Path]:
    """Every entry-point binary install.sh / pipx have ever produced for the
    client. We try them all — a no-op if the file doesn't exist."""
    if sys.platform == "win32":
        prog = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        p = Path(prog) / "OutWarp" / "outwarp.bat"
        return [p] if p.exists() else []
    if sys.platform == "linux":
        candidates = [
            Path("/usr/local/bin/outwarp"),
            Path("/usr/local/bin/outwarp-cli"),
            Path("/usr/local/bin/outwarp-uninstall"),
        ]
        return [p for p in candidates if p.exists()]
    return []


def _extra_artifacts() -> list[Path]:
    """Files outside the venv prefix and shims that install.sh writes —
    the privileged helper, sudoers rule, and the 0.4.x autostart entry that
    0.5.x's install.sh sweeps but a fresh `uninstall` should also reach."""
    if sys.platform != "linux":
        return []
    paths = [
        Path("/usr/local/libexec/outwarp-priv"),
        Path("/etc/sudoers.d/outwarp"),
    ]
    target_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    if target_user and target_user != "root":
        home = Path(f"/home/{target_user}")
        if not home.exists():
            home = Path(os.path.expanduser(f"~{target_user}"))
        paths.append(home / ".config" / "autostart" / "outwarp.desktop")
    return [p for p in paths if p.exists()]


def _config_dir() -> Path | None:
    try:
        from platformdirs import user_config_dir
        return Path(user_config_dir("OutWarp"))
    except Exception:
        return None


def _startup_shortcut() -> Path | None:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return (
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu"
                / "Programs" / "Startup" / "OutWarp.lnk"
            )
    return None


def _desktop_shortcut() -> Path | None:
    if sys.platform == "win32":
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            return Path(userprofile) / "Desktop" / "OutWarp.lnk"
    return None


# ---------------------------------------------------------------------------
# Kill running instance
# ---------------------------------------------------------------------------

def _kill_running() -> None:
    """Best-effort: terminate any outwarp process before deleting files."""
    try:
        if sys.platform == "win32":
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/IM", "outwarp.exe"],
                capture_output=True,
            )
        else:
            import subprocess
            subprocess.run(["pkill", "-f", "outwarp"], capture_output=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Deferred cleanup — deletes venv+shim after this process exits
# (we can't delete the tree we're running from while we're in it)
# ---------------------------------------------------------------------------

def _spawn_deferred_cleanup_windows(prefixes: list[Path], shims: list[Path]) -> None:
    import subprocess
    import tempfile

    pid = os.getpid()
    lines = [f'rmdir /s /q "{p}"' for p in prefixes]
    lines += [f'del /f /q "{s}"' for s in shims]

    script = (
        "@echo off\r\n"
        ":wait\r\n"
        f"tasklist /FI \"PID eq {pid}\" 2>nul | find \"{pid}\" >nul && goto wait\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        + "\r\n".join(lines)
        + "\r\ndel /f /q \"%~f0\"\r\n"
    )
    fd, script_path = tempfile.mkstemp(prefix="outwarp-uninstall-", suffix=".bat")
    with os.fdopen(fd, "w") as f:
        f.write(script)

    subprocess.Popen(
        ["cmd.exe", "/c", script_path],
        creationflags=0x00000008,  # DETACHED_PROCESS
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _spawn_deferred_cleanup_posix(prefixes: list[Path], shims: list[Path]) -> None:
    import shlex
    import subprocess
    import tempfile

    pid = os.getpid()
    lines = [f"rm -rf {shlex.quote(str(p))}" for p in prefixes]
    lines += [f"rm -f {shlex.quote(str(s))}" for s in shims]

    script = (
        "#!/usr/bin/env bash\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
        "sleep 1\n"
        + "\n".join(lines)
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="outwarp-cli uninstall",
        description="Remove all OutWarp client files installed by the official installer.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    args = parser.parse_args(argv)

    _require_admin()
    _confirm(args.yes)

    warnings: list[str] = []

    def step(label: str, fn) -> None:
        print(f"  {label}...", end=" ", flush=True)
        try:
            fn()
            print("done")
        except Exception as exc:
            print(f"warning: {exc}")
            warnings.append(f"{label}: {exc}")

    _kill_running()

    config = _config_dir()
    startup = _startup_shortcut()
    desktop = _desktop_shortcut()
    prefixes = _client_prefixes()
    shims = _client_shims()
    extras = _extra_artifacts()

    if config and config.exists():
        step(f"Removing config/logs ({config})", lambda: shutil.rmtree(config))

    if startup and startup.exists():
        step("Removing startup shortcut", startup.unlink)

    if desktop and desktop.exists():
        step("Removing desktop shortcut", desktop.unlink)

    for extra in extras:
        step(f"Removing {extra}", extra.unlink)

    # The venv prefixes and shims live in the tree we're running from, so they
    # have to wait until this process exits — a detached script does the work.
    if prefixes:
        try:
            if sys.platform == "win32":
                _spawn_deferred_cleanup_windows(prefixes, shims)
            else:
                _spawn_deferred_cleanup_posix(prefixes, shims)
            removed = ", ".join(str(p) for p in prefixes + shims)
            print(f"  Scheduled removal of {removed} after exit... done")
        except Exception as exc:
            warnings.append(f"deferred cleanup: {exc}")
            print(f"  Scheduling deferred cleanup... warning: {exc}")
    else:
        for shim in shims:
            step(f"Removing binary ({shim})", shim.unlink)

    print()
    if warnings:
        print(f"Uninstall completed with {len(warnings)} warning(s) — see above.")
        return 1

    print("OutWarp client uninstalled successfully.")
    if sys.platform == "win32":
        print(
            "You can also remove WireGuard for Windows from Add/Remove Programs "
            "if no longer needed.",
        )
    return 0
