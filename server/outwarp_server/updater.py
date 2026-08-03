"""GitHub Releases based updater for the OutWarp server (Linux wheels).

Mirrors the client-side updater but only carries what the server needs:
locate the latest ``outwarp_server-*.whl`` asset, verify its SHA-256 against
the release's ``SHA256SUMS.txt``, and ``pip install --upgrade`` into the
currently running venv. Stdlib-only so it's trivially unit-testable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
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
_CHECKSUMS_ASSET = "SHA256SUMS.txt"
_SIGNATURE_ASSET = "SHA256SUMS.txt.minisig"

# See the identical constant in client/outwarp/updater.py: the release-signing
# public key (key ID 3E1FCD8BF652EC28) is compiled in and its private half lives
# offline. Because it is set, an unsigned or wrongly-signed manifest is rejected.
_MINISIGN_PUBLIC_KEY = (
    "untrusted comment: minisign public key 3E1FCD8BF652EC28\n"
    "RWQo7FL2i80fPrFtvv7gB5xJCqS/7KTSu+VkoLRdnaQyTnwXXuemHydR\n"
)


def signing_configured() -> bool:
    return bool(_MINISIGN_PUBLIC_KEY.strip())
_SERVER_WHEEL_RE = re.compile(r"^outwarp[_-]server-[0-9].*\.whl$", re.IGNORECASE)


def _parse_version(s: str) -> tuple[int, ...]:
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
    n = max(len(lv), len(cv))
    lv += (0,) * (n - len(lv))
    cv += (0,) * (n - len(cv))
    return lv > cv


def check_for_update(current: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Query GitHub Releases for the latest ``outwarp-server`` wheel.

    Never raises - any network/parse error returns ``{"available": False,
    "error": "<msg>"}`` so callers can surface a friendly message instead of
    crashing the CLI.
    """
    try:
        req = urllib.request.Request(_LATEST_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        log.warning("update check failed: %s", exc)
        return {"available": False, "current": current, "error": str(exc)}

    latest = str(data.get("tag_name") or "").lstrip("vV")
    html_url = str(data.get("html_url") or _RELEASES_PAGE)
    assets = data.get("assets") or []

    wheel: dict[str, Any] | None = None
    for asset in assets:
        if _SERVER_WHEEL_RE.match(str(asset.get("name") or "")):
            wheel = asset
            break

    checksums_url = _asset_url(assets, _CHECKSUMS_ASSET)
    signature_url = _asset_url(assets, _SIGNATURE_ASSET)

    wheel_url = str(wheel.get("browser_download_url") or "") if wheel else ""
    wheel_name = str(wheel.get("name") or "") if wheel else ""
    wheel_size = int(wheel.get("size") or 0) if wheel else 0

    return {
        "available": bool(latest) and _is_newer(latest, current) and bool(wheel_url),
        "current": current,
        "latest": latest,
        "wheel_url": wheel_url,
        "wheel_name": wheel_name,
        "wheel_size": wheel_size,
        "checksums_url": checksums_url,
        "signature_url": signature_url,
        "html_url": html_url,
    }


def download_wheel(
    url: str,
    dest: Path,
    progress_cb: Callable[[int], None] | None = None,
    *,
    timeout: float = 60.0,
    chunk_size: int = 64 * 1024,
) -> Path:
    """Stream the wheel from ``url`` into ``dest``, invoking ``progress_cb(percent)``."""
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


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_checksums(text: str) -> dict[str, str]:
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


def _asset_url(assets: list, name: str) -> str:
    for a in assets:
        if str(a.get("name") or "").lower() == name.lower():
            return str(a.get("browser_download_url") or "")
    return ""


def _verify_manifest_signature(manifest: str, signature_url: str) -> None:
    """Raise ValueError unless the manifest carries a valid release signature.

    No-op while no key is compiled in. Once one is, a missing or unfetchable
    signature is as fatal as a bad one: the check must not be defeatable by
    deleting a file from the release.
    """
    if not signing_configured():
        return
    if not signature_url:
        raise ValueError(
            f"the release does not publish {_SIGNATURE_ASSET}; refusing to trust "
            "an unsigned manifest"
        )
    try:
        req = urllib.request.Request(signature_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            signature = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ValueError(f"could not fetch {_SIGNATURE_ASSET}: {exc}") from exc

    from outwarp_server.minisign import MinisignError, verify
    try:
        verify(manifest.encode("utf-8"), signature, _MINISIGN_PUBLIC_KEY)
    except MinisignError as exc:
        raise ValueError(str(exc)) from exc


def verify_wheel(
    path: Path, asset_name: str, checksums_url: str, signature_url: str = ""
) -> tuple[bool, str]:
    """Verify ``path`` against the release's published SHA256SUMS.

    Returns ``(ok, detail)``. Decisions:

    - No ``checksums_url`` (the release has no manifest at all): skip with
      ``ok=True``. Legacy releases predate the manifest and we don't want
      ``outwarp-server update`` to refuse to upgrade off them.
    - Manifest URL present but fetch fails: ``ok=False``. A MITM that can
      selectively drop the manifest must not be able to downgrade verification.
    - Manifest fetched but this asset isn't listed: ``ok=False``. If the
      release publisher took the trouble of attaching a manifest, every wheel
      they're publishing should be in it; a missing entry means we're looking
      at the wrong release or a tampered manifest.
    - Manifest fetched, asset listed, hash mismatches: ``ok=False``.
    """
    if not checksums_url:
        if signing_configured():
            return False, "the release publishes no SHA256SUMS to verify against"
        return True, "no SHA256SUMS published (skipping verification)"
    try:
        req = urllib.request.Request(checksums_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log.warning("could not fetch checksums: %s", exc)
        return False, f"could not fetch SHA256SUMS: {exc}"

    # Authenticate before parsing: the hashes are only worth reading once we
    # know who wrote them.
    try:
        _verify_manifest_signature(text, signature_url)
    except ValueError as exc:
        return False, f"SHA256SUMS failed signature verification: {exc}"
    sums = _parse_checksums(text)

    expected = sums.get(asset_name)
    if not expected:
        return False, f"{asset_name} is not listed in SHA256SUMS"

    actual = _sha256_file(path)
    if actual.lower() == expected.lower():
        return True, "sha256 verified"
    return False, f"sha256 mismatch: expected {expected[:16]}…, got {actual[:16]}…"


PIP_INSTALL_TIMEOUT = 600.0
"""Seconds before ``pip install`` is killed — see
``outwarp.updater.PIP_INSTALL_TIMEOUT`` for the rationale."""


def apply_update(
    wheel_path: Path,
    extras: str = "",
    *,
    timeout: float = PIP_INSTALL_TIMEOUT,
) -> None:
    """Install ``wheel_path`` into the current venv via ``pip install --upgrade``.

    Uses ``sys.executable`` so this always targets the venv that's running
    this code, even when invoked via ``sudo outwarp-server update``. Under
    the pipx-managed layout (``PIPX_HOME=/opt/pipx``), that venv lives at
    ``/opt/pipx/venvs/outwarp-server/`` and pip inside it works as in any
    plain venv — we deliberately do NOT shell out to ``pipx upgrade`` because
    that would re-bootstrap the venv from the original spec and lose any
    operator-injected debug packages. Raises
    ``subprocess.CalledProcessError`` on pip failure or
    ``subprocess.TimeoutExpired`` if pip is still running after ``timeout``
    seconds — protects against a stalled PyPI fetch hanging the CLI forever.
    """
    target = str(wheel_path)
    if extras:
        target = f"{target}[{extras}]"
    subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--upgrade", "--disable-pip-version-check", "--quiet", target],
        check=True,
        timeout=timeout,
    )
