"""
In-app updater for the OutWarp client.

Pure logic for querying GitHub Releases and downloading the Windows installer.
The platform-specific "apply" step (launch the installer, then quit so it can
replace our files) lives in api.py, which imports from here. This module is
OS-agnostic and stdlib-only so it stays unit-testable on any platform.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REPO = "fcrespo07/OutWarp"
_LATEST_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_RELEASES_PAGE = f"https://github.com/{_REPO}/releases/latest"
_USER_AGENT = "OutWarp-Updater"

# Plain-text manifest (one "<sha256>  <filename>" line per asset, sha256sum
# format) that build.py generates and the release publishes alongside the
# installers. The updater verifies the downloaded .exe against it before
# launching it, so a tampered or truncated download is rejected instead of run.
_CHECKSUMS_ASSET = "SHA256SUMS.txt"

# Windows installer asset names produced by build.py (outwarp.iss
# OutputBaseFilename per edition). The client prefers the slim "Client" edition
# (~half the size — it omits the server's PyInstaller bundle) and falls back to
# the combined installer for releases published before the split. It never picks
# the server edition.
_CLIENT_ASSET_RE = re.compile(r"^OutWarpSetup-Client-.*\.exe$", re.IGNORECASE)
_FULL_ASSET_RE = re.compile(r"^OutWarpSetup-(?!Client-)(?!Server-).*\.exe$", re.IGNORECASE)


def _select_installer_asset(
    assets: list[dict[str, Any]], *, prefer_full: bool = False
) -> dict[str, Any] | None:
    # prefer_full is set when the server is co-installed on this machine: the
    # slim client edition would leave that server bundle stale, so fall back to
    # the combined installer which updates both.
    order = (
        (_FULL_ASSET_RE, _CLIENT_ASSET_RE) if prefer_full
        else (_CLIENT_ASSET_RE, _FULL_ASSET_RE)
    )
    for pattern in order:
        for asset in assets:
            if pattern.match(str(asset.get("name") or "")):
                return asset
    return None

# Mirrors the documented one-liner in installer/linux/install.sh. Shown to the
# user on Linux, where there is no .exe to auto-apply and the GUI cannot run a
# non-interactive sudo for an arbitrary install.
LINUX_UPDATE_COMMAND = (
    "curl -fsSL https://raw.githubusercontent.com/fcrespo07/OutWarp/main/"
    "installer/linux/install.sh | sudo bash"
)


def _parse_version(s: str) -> tuple[int, ...]:
    """Parse 'v0.1.10' / '0.1.10' into (0, 1, 10). Stops at the first chunk
    that doesn't start with a digit so a '-rc1' style suffix is ignored."""
    s = s.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in s.split("."):
        m = re.match(r"\d+", chunk)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    lv, cv = _parse_version(latest), _parse_version(current)
    if not lv:
        return False
    # Pad to equal length so (0, 1) compares correctly against (0, 1, 0) and
    # numeric components compare as ints (0.1.10 > 0.1.9).
    n = max(len(lv), len(cv))
    lv += (0,) * (n - len(lv))
    cv += (0,) * (n - len(cv))
    return lv > cv


def check_for_update(
    current: str, *, timeout: float = 5.0, prefer_full: bool = False
) -> dict[str, Any]:
    """Query GitHub Releases for the latest version.

    Never raises: any network/parse failure returns
    ``{"available": False, "error": "<msg>"}`` so the bridge can surface a soft
    message instead of crashing the renderer.

    prefer_full picks the combined installer over the slim client edition (set
    when a server is co-installed — see Api._prefer_full_installer).
    """
    try:
        req = urllib.request.Request(_LATEST_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        log.warning("update check failed: %s", exc)
        return {"available": False, "current": current, "error": str(exc)}

    latest = str(data.get("tag_name") or "").lstrip("vV")
    notes = str(data.get("body") or "").strip()
    html_url = str(data.get("html_url") or _RELEASES_PAGE)

    assets = data.get("assets") or []
    asset = _select_installer_asset(assets, prefer_full=prefer_full)
    asset_url = str(asset.get("browser_download_url") or "") if asset else ""
    asset_name = str(asset.get("name") or "") if asset else ""
    asset_size = int(asset.get("size") or 0) if asset else 0

    checksums_url = ""
    for a in assets:
        if str(a.get("name") or "").lower() == _CHECKSUMS_ASSET.lower():
            checksums_url = str(a.get("browser_download_url") or "")
            break

    return {
        "available": bool(latest) and _is_newer(latest, current),
        "current": current,
        "latest": latest,
        "notes": notes,
        "asset_url": asset_url,
        "asset_name": asset_name,
        "asset_size": asset_size,
        "checksums_url": checksums_url,
        "html_url": html_url,
    }


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the lowercase hex SHA-256 of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    """Parse a sha256sum-format manifest into {filename: lowercase_hex_sha256}.

    Tolerates both "<hex>  name" and "<hex> *name" (binary marker), extra
    whitespace, and a leading "./" on names. Lines that don't match are skipped.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([0-9A-Fa-f]{64})[ \t]+\*?(.+)$", line)
        if not m:
            continue
        name = m.group(2).strip().lstrip("./").replace("\\", "/").split("/")[-1]
        out[name] = m.group(1).lower()
    return out


def fetch_checksums(url: str, *, timeout: float = 10.0) -> dict[str, str]:
    """Download and parse the SHA256SUMS manifest. Returns {} on any failure."""
    if not url:
        return {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_checksums(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        log.warning("could not fetch checksums: %s", exc)
        return {}


def verify_download(path: Path, asset_name: str, checksums_url: str) -> tuple[bool, str]:
    """Check `path` against the published SHA256SUMS.

    Returns (ok, detail). ok is True when the hash matches OR when no checksum
    is available for this asset (older releases predate the manifest — we don't
    block them). ok is False only on a real mismatch, which the caller must
    treat as a failed/compromised download and refuse to run.
    """
    sums = fetch_checksums(checksums_url)
    expected = sums.get(asset_name)
    if not expected:
        return True, "no checksum published for this asset (skipping verification)"
    actual = sha256_file(path)
    if actual.lower() == expected.lower():
        return True, "sha256 verified"
    return False, f"sha256 mismatch: expected {expected[:16]}…, got {actual[:16]}…"


def download_installer(
    url: str,
    dest: Path,
    progress_cb: Callable[[int], None] | None = None,
    *,
    timeout: float = 30.0,
    chunk_size: int = 64 * 1024,
) -> Path:
    """Stream `url` to `dest`, invoking ``progress_cb(percent)`` (0-100) as it
    downloads. Returns the destination path. Raises on network/IO error — the
    caller (Api.apply_update) catches and reports it via outwarp:update."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        last_pct = -1
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                read += len(chunk)
                if progress_cb is not None and total > 0:
                    pct = min(100, int(read * 100 / total))
                    if pct != last_pct:
                        last_pct = pct
                        progress_cb(pct)
    if progress_cb is not None:
        progress_cb(100)
    return dest
