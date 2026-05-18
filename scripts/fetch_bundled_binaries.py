"""Download external binaries that the Windows installer bundles.

The Inno Setup installer in installer/windows/outwarp.iss ships two
third-party binaries alongside OutWarp:

  - wstunnel.exe      (BSD-3-Clause, from github.com/erebe/wstunnel)
  - WireGuard.msi     (GPL-2.0, invoked at install time via msiexec; not
                       linked, see CLAUDE.md "Licencias")

Both end up in installer/windows/bundle/ (gitignored) so the .iss script
can reference them with a stable relative path.

Usage:
    python scripts/fetch_bundled_binaries.py
    python scripts/fetch_bundled_binaries.py --skip-wireguard
    WSTUNNEL_VERSION=v10.5.2 python scripts/fetch_bundled_binaries.py

The script is idempotent: if the file is already present it skips the
download unless --force is given.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = ROOT / "installer" / "windows" / "bundle"

WSTUNNEL_DEFAULT_VERSION = "v10.5.2"
WIREGUARD_MSI_URL = "https://download.wireguard.com/windows-client/wireguard-installer.exe"
# WireGuard publishes both .msi and .exe installers; the .exe is the canonical
# one and supports silent install via /S. Newer hashes break across releases —
# we don't pin a hash to avoid blocking unattended builds when a new version drops.


def _download(url: str, dest: Path, label: str) -> None:
    print(f"  downloading {label} ({url})")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)
    size_kb = dest.stat().st_size // 1024
    print(f"  -> {dest.name} ({size_kb} KB)")


def fetch_wstunnel(version: str, *, force: bool) -> None:
    out_path = BUNDLE_DIR / "wstunnel.exe"
    if out_path.exists() and not force:
        print(f"[wstunnel] already present at {out_path} (use --force to redownload)")
        return

    vnum = version.lstrip("v")
    tarball = f"wstunnel_{vnum}_windows_amd64.tar.gz"
    url = f"https://github.com/erebe/wstunnel/releases/download/{version}/{tarball}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tarball_path = tmp_path / tarball
        _download(url, tarball_path, f"wstunnel {version}")
        with tarfile.open(tarball_path) as tf:
            members = [m for m in tf.getmembers() if m.name.endswith("wstunnel.exe")]
            if not members:
                raise SystemExit(f"wstunnel.exe not found inside {tarball}")
            tf.extract(members[0], path=tmp_path)
            extracted = tmp_path / members[0].name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted, out_path)
    size_kb = out_path.stat().st_size // 1024
    print(f"[wstunnel] -> {out_path} ({size_kb} KB)")


def fetch_wireguard(*, force: bool) -> None:
    out_path = BUNDLE_DIR / "wireguard-installer.exe"
    if out_path.exists() and not force:
        print(f"[wireguard] already present at {out_path} (use --force to redownload)")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _download(WIREGUARD_MSI_URL, out_path, "WireGuard")
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[wireguard] -> {out_path} ({size_mb:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="redownload even if files already exist")
    ap.add_argument("--skip-wireguard", action="store_true", help="skip WireGuard installer download")
    ap.add_argument("--skip-wstunnel", action="store_true", help="skip wstunnel download")
    ap.add_argument(
        "--wstunnel-version",
        default=os.environ.get("WSTUNNEL_VERSION", WSTUNNEL_DEFAULT_VERSION),
        help=f"wstunnel release tag (default: {WSTUNNEL_DEFAULT_VERSION}, or $WSTUNNEL_VERSION)",
    )
    args = ap.parse_args()

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"target: {BUNDLE_DIR}")

    if not args.skip_wstunnel:
        fetch_wstunnel(args.wstunnel_version, force=args.force)
    if not args.skip_wireguard:
        fetch_wireguard(force=args.force)

    print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
