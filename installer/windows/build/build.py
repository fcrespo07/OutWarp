"""Orchestrate the Windows build: UI bundle -> PyInstaller -> Inno Setup.

Run this from any working directory; paths are resolved relative to the
repo root.

Pipeline:
  1. scripts/build_ui.py            (esbuild — requires Node on PATH)
  2. scripts/fetch_bundled_binaries.py
                                    (downloads wstunnel.exe + WireGuard)
  3. PyInstaller × 2                (client, server [GUI + CLI in one bundle])
  4. (optional) ISCC outwarp.iss    (Inno Setup compiler — must be on PATH)

Usage:
    python installer/windows/build/build.py
    python installer/windows/build/build.py --skip-ui --skip-fetch
    python installer/windows/build/build.py --no-installer
    python installer/windows/build/build.py --version 0.1.1

The final OutWarpSetup-<version>.exe lands in installer/windows/output/.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTALLER_DIR = ROOT / "installer" / "windows"
BUILD_DIR = INSTALLER_DIR / "build"
DIST_DIR = ROOT / "dist"
WORK_DIR = ROOT / "build"

SPECS = [
    BUILD_DIR / "outwarp-client.spec",
    BUILD_DIR / "outwarp-server.spec",
]


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"command failed (exit {result.returncode}): {' '.join(cmd)}")


def _ensure_pyinstaller() -> str:
    """Return the python -m PyInstaller command, installing if missing."""
    try:
        import PyInstaller  # noqa: F401
        return sys.executable
    except ImportError:
        print("[pre-flight] PyInstaller not found, installing into the current interpreter")
        _run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller>=6.0"])
        return sys.executable


def _ensure_runtime_deps(python_bin: str) -> None:
    """Make sure the client + server runtime deps are importable.

    PyInstaller only bundles what's physically importable in the current
    interpreter at Analysis time. If pywebview / pystray / cryptography /
    etc. aren't installed, the resulting .exe imports them at runtime
    and crashes with ModuleNotFoundError. Install both packages in
    editable mode so any imports they declare are resolvable.
    """
    print("\n=== [pre-flight] installing client + server[gui] runtime deps ===")
    _run([python_bin, "-m", "pip", "install", "--upgrade", "pip"])
    _run([python_bin, "-m", "pip", "install", "-e", str(ROOT / "client")])
    _run([python_bin, "-m", "pip", "install", "-e", f"{ROOT / 'server'}[gui]"])


def step_ui() -> None:
    print("\n=== [1/4] building UI bundles (esbuild) ===")
    _run([sys.executable, str(ROOT / "scripts" / "build_ui.py")])


def step_fetch() -> None:
    print("\n=== [2/4] fetching wstunnel + WireGuard ===")
    _run([sys.executable, str(ROOT / "scripts" / "fetch_bundled_binaries.py")])


def step_pyinstaller(python_bin: str, *, clean: bool) -> None:
    print("\n=== [3/4] running PyInstaller (client + server) ===")
    if clean:
        for d in (DIST_DIR, WORK_DIR):
            if d.exists():
                print(f"  cleaning {d}")
                shutil.rmtree(d)
    for spec in SPECS:
        if not spec.exists():
            raise SystemExit(f"missing spec file: {spec}")
        _run([python_bin, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)], cwd=ROOT)


def step_installer(version: str) -> None:
    print("\n=== [4/4] building Inno Setup installer ===")
    iss = INSTALLER_DIR / "outwarp.iss"
    if not iss.exists():
        raise SystemExit(f"missing Inno Setup script: {iss}")
    iscc = shutil.which("iscc") or shutil.which("ISCC")
    if iscc is None:
        # Common install locations for Inno Setup 6 (system-wide and per-user).
        candidates = [
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
        ]
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(str(Path(local_appdata) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
        for candidate in candidates:
            if Path(candidate).exists():
                iscc = candidate
                break
    if iscc is None:
        raise SystemExit(
            "ISCC.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php "
            "or rerun with --no-installer."
        )
    _run([iscc, f"/DAppVersion={version}", str(iss)])
    out = INSTALLER_DIR / "output"
    print(f"\n  installer written to: {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=os.environ.get("OUTWARP_VERSION", "0.1.2"))
    ap.add_argument("--skip-ui", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-pyinstaller", action="store_true")
    ap.add_argument("--no-installer", action="store_true", help="stop after PyInstaller")
    ap.add_argument("--no-clean", action="store_true", help="keep previous dist/ and build/ contents")
    args = ap.parse_args()

    python_bin = _ensure_pyinstaller()

    if not args.skip_ui:
        step_ui()
    if not args.skip_fetch:
        step_fetch()
    if not args.skip_pyinstaller:
        _ensure_runtime_deps(python_bin)
        step_pyinstaller(python_bin, clean=not args.no_clean)
    if not args.no_installer:
        step_installer(args.version)

    print("\nbuild finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
