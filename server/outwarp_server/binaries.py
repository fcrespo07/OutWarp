"""Locate the external binaries OutWarp drives (wstunnel, wg).

Centralised so the GUI works without anything on PATH: the Windows installer
no longer adds {app} to the system PATH, so discovery has to fall back to the
bundle layout (wstunnel.exe sits next to / one level above the frozen .exe)
and to each tool's well-known install location (WireGuard ships wg.exe under
C:\\Program Files\\WireGuard, which is not on PATH by default).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _frozen_dirs() -> list[Path]:
    """Directories to probe for bundled binaries when running as a PyInstaller
    one-folder build: the exe's own dir and its parent (the shared install root
    where the installer drops wstunnel.exe)."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        return [exe_dir, exe_dir.parent]
    return []


def find_wstunnel() -> Path | None:
    name = "wstunnel.exe" if sys.platform == "win32" else "wstunnel"
    for d in _frozen_dirs():
        candidate = d / name
        if candidate.exists():
            return candidate
    on_path = shutil.which("wstunnel")
    return Path(on_path) if on_path else None


_WIN_WG_PATHS = (
    r"C:\Program Files\WireGuard\wg.exe",
    r"C:\Program Files (x86)\WireGuard\wg.exe",
)
_POSIX_WG_PATHS = ("/usr/bin/wg", "/usr/local/bin/wg", "/sbin/wg")


def find_wg() -> Path | None:
    on_path = shutil.which("wg")
    if on_path:
        return Path(on_path)
    candidates = _WIN_WG_PATHS if sys.platform == "win32" else _POSIX_WG_PATHS
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None
