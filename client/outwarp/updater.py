"""
In-app updater for the OutWarp client.

Pure logic for querying GitHub Releases and downloading the Windows installer.
The platform-specific "apply" step (launch the installer, then quit so it can
replace our files) lives in api.py, which imports from here. This module is
OS-agnostic and stdlib-only so it stays unit-testable on any platform.
"""

from __future__ import annotations

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

# The Windows installer asset name produced by build.py, e.g.
# "OutWarpSetup-0.1.5.exe" (see installer/windows/outwarp.iss OutputBaseFilename).
_ASSET_RE = re.compile(r"^OutWarpSetup-.*\.exe$", re.IGNORECASE)

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


def check_for_update(current: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Query GitHub Releases for the latest version.

    Never raises: any network/parse failure returns
    ``{"available": False, "error": "<msg>"}`` so the bridge can surface a soft
    message instead of crashing the renderer.
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

    asset_url = ""
    asset_name = ""
    asset_size = 0
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if _ASSET_RE.match(name):
            asset_url = str(asset.get("browser_download_url") or "")
            asset_name = name
            asset_size = int(asset.get("size") or 0)
            break

    return {
        "available": bool(latest) and _is_newer(latest, current),
        "current": current,
        "latest": latest,
        "notes": notes,
        "asset_url": asset_url,
        "asset_name": asset_name,
        "asset_size": asset_size,
        "html_url": html_url,
    }


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
