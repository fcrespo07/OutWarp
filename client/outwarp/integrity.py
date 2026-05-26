"""Startup integrity check for the files OutWarp depends on.

Catches the most common breakage seen in real-world Windows deployments:
``wstunnel.exe`` (and occasionally other bundled binaries) get silently
quarantined by Defender as ``HackTool:Win32/Wstunnel``. The user opens
OutWarp, clicks Connect, and watches a generic "could not start tunnel"
error roll past without any hint of *why*. Verifying the critical files
at startup turns that into a clear, specific banner.

Cheap by design: only a handful of ``stat()`` calls, no hashing. Cost is
in the low milliseconds even on a slow disk, so it can run synchronously
before the window is shown without any user-visible latency.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from outwarp.tunnel import TunnelError, find_wstunnel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrityIssue:
    """One missing/empty file. Multiple issues can be reported per check."""

    name: str        # short logical id, e.g. "wstunnel", "ui/index.html"
    path: str        # absolute path attempted ("" when we never resolved one)
    kind: str        # "missing" | "empty"
    detail: str      # human-readable, log-friendly

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "detail": self.detail,
        }


def check_critical_files() -> list[IntegrityIssue]:
    """Return a list of integrity issues. Empty list means everything is OK.

    Never raises — any unexpected error is captured as an "unknown" issue so a
    bug in this module can't gate the whole app's startup.
    """
    issues: list[IntegrityIssue] = []
    try:
        issues.extend(_check_wstunnel())
        issues.extend(_check_ui_bundle())
        if sys.platform == "win32":
            issues.extend(_check_wireguard_windows())
    except Exception as exc:
        log.exception("integrity check crashed")
        issues.append(IntegrityIssue(
            name="integrity-check",
            path="",
            kind="unknown",
            detail=str(exc),
        ))
    return issues


def _check_wstunnel() -> list[IntegrityIssue]:
    try:
        return _stat_check("wstunnel", find_wstunnel())
    except TunnelError as exc:
        return [IntegrityIssue(
            name="wstunnel",
            path="",
            kind="missing",
            detail=str(exc),
        )]


def _check_ui_bundle() -> list[IntegrityIssue]:
    """Files the renderer fetches before doing anything else. If any is gone
    we'd otherwise show a blank window with no log line to grep for."""
    ui_dir = _resolve_ui_dir()
    issues: list[IntegrityIssue] = []
    for rel in ("index.html", "bundle.js", "styles.css"):
        issues.extend(_stat_check(f"ui/{rel}", ui_dir / rel))
    return issues


def _check_wireguard_windows() -> list[IntegrityIssue]:
    # Imported lazily so the Linux path doesn't touch the Windows module.
    from outwarp.platforms.windows import _WIREGUARD_EXE  # noqa: PLC2701

    return _stat_check("wireguard.exe", _WIREGUARD_EXE)


def _stat_check(name: str, path: Path) -> list[IntegrityIssue]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return [IntegrityIssue(
            name=name,
            path=str(path),
            kind="missing",
            detail=f"{path} not found",
        )]
    except OSError as exc:
        return [IntegrityIssue(
            name=name,
            path=str(path),
            kind="missing",
            detail=str(exc),
        )]
    if st.st_size == 0:
        return [IntegrityIssue(
            name=name,
            path=str(path),
            kind="empty",
            detail=f"{path} is empty (likely partial quarantine)",
        )]
    return []


def _resolve_ui_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).parent / "ui"


def likely_av_quarantine(issues: list[IntegrityIssue]) -> bool:
    """True iff the report looks like Defender (or similar) ate a critical
    binary. Used by the UI to show the AV-specific guidance instead of a
    generic 'something is missing' message."""
    av_targets = {"wstunnel", "wireguard.exe"}
    return any(i.name in av_targets for i in issues)


def format_report(issues: list[IntegrityIssue]) -> str:
    """Multi-line, log-friendly summary."""
    if not issues:
        return "integrity ok"
    lines = [f"integrity check found {len(issues)} issue(s):"]
    for i in issues:
        lines.append(f"  - [{i.kind}] {i.name}: {i.detail}")
    return "\n".join(lines)
