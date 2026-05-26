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


def _resolve_iscc() -> str:
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
    return iscc


def step_installer(version: str, editions: list[str]) -> None:
    print("\n=== [4/4] building Inno Setup installer(s) ===")
    iss = INSTALLER_DIR / "outwarp.iss"
    if not iss.exists():
        raise SystemExit(f"missing Inno Setup script: {iss}")
    iscc = _resolve_iscc()
    # full = client + server in one .exe (first-install / both on one machine);
    # client / server = slim editions that omit the other app's PyInstaller
    # bundle, halving the download. The in-app client updater fetches "client".
    for edition in editions:
        print(f"\n  -> edition: {edition}")
        _run([iscc, f"/DAppVersion={version}", f"/DEdition={edition}", str(iss)])
    out = INSTALLER_DIR / "output"
    print(f"\n  installer(s) written to: {out}")


def _resolve_signtool() -> str | None:
    tool = shutil.which("signtool")
    if tool:
        return tool
    # signtool ships with the Windows SDK; probe the usual install roots.
    import glob
    for root in (
        r"C:\Program Files (x86)\Windows Kits\10\bin",
        r"C:\Program Files\Windows Kits\10\bin",
    ):
        hits = sorted(glob.glob(rf"{root}\*\x64\signtool.exe"))
        if hits:
            return hits[-1]
    return None


def step_sign(version: str) -> None:
    """Authenticode-sign the per-edition installers if a cert is configured.

    Opt-in and safe to leave off: with no cert env vars set this is a logged
    no-op (OutWarp ships unsigned today — see CLAUDE.md). Configure either:
      OUTWARP_SIGN_PFX + OUTWARP_SIGN_PASS   (a .pfx file + its password), or
      OUTWARP_SIGN_SHA1                       (thumbprint of a cert in the store)
    Runs before step_checksums so SHA256SUMS.txt covers the signed bytes.
    """
    pfx = os.environ.get("OUTWARP_SIGN_PFX")
    sha1 = os.environ.get("OUTWARP_SIGN_SHA1")
    if not pfx and not sha1:
        print("  no signing cert configured (OUTWARP_SIGN_PFX / OUTWARP_SIGN_SHA1) — "
              "leaving installers unsigned")
        return
    signtool = _resolve_signtool()
    if signtool is None:
        raise SystemExit("signing requested but signtool.exe not found (install the Windows SDK)")

    out = INSTALLER_DIR / "output"
    installers = sorted(out.glob(f"OutWarpSetup-*{version}*.exe"))
    if not installers:
        raise SystemExit(f"no installers found in {out} to sign")

    base = [signtool, "sign", "/fd", "sha256", "/tr",
            "http://timestamp.digicert.com", "/td", "sha256"]
    if pfx:
        base += ["/f", pfx]
        if os.environ.get("OUTWARP_SIGN_PASS"):
            base += ["/p", os.environ["OUTWARP_SIGN_PASS"]]
    else:
        base += ["/sha1", sha1]

    for exe in installers:
        print(f"  signing {exe.name}")
        _run([*base, str(exe)])


def step_checksums(version: str) -> Path:
    """Write output/SHA256SUMS.txt covering every OutWarpSetup-*<version>*.exe.

    The in-app client updater downloads this manifest and verifies the
    installer's SHA-256 against it before launching — so the release MUST
    attach this file alongside the installers.
    """
    import hashlib

    out = INSTALLER_DIR / "output"
    installers = sorted(out.glob(f"OutWarpSetup-*{version}*.exe"))
    if not installers:
        raise SystemExit(f"no installers found in {out} to checksum")
    lines = []
    for exe in installers:
        h = hashlib.sha256()
        with open(exe, "rb") as fh:
            for chunk in iter(lambda fh=fh: fh.read(1024 * 1024), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {exe.name}")
        print(f"  {exe.name}: {h.hexdigest()}")
    manifest = out / "SHA256SUMS.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n  checksums written to: {manifest}")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=os.environ.get("OUTWARP_VERSION", "0.4.0"))
    ap.add_argument("--skip-ui", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-pyinstaller", action="store_true")
    ap.add_argument("--no-installer", action="store_true", help="stop after PyInstaller")
    ap.add_argument("--no-clean", action="store_true", help="keep previous dist/ and build/ contents")
    ap.add_argument(
        "--editions",
        default="full,client,server",
        help="comma-separated installer editions to build (full,client,server)",
    )
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
        editions = [e.strip() for e in args.editions.split(",") if e.strip()]
        unknown = [e for e in editions if e not in ("full", "client", "server")]
        if unknown:
            raise SystemExit(f"unknown edition(s): {', '.join(unknown)} (expected full/client/server)")
        step_installer(args.version, editions)
        print("\n=== signing installers (if a cert is configured) ===")
        step_sign(args.version)
        print("\n=== generating SHA256SUMS.txt ===")
        step_checksums(args.version)

    print("\nbuild finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
