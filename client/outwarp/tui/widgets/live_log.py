from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from textual.widgets import RichLog

from outwarp.logs import tail_follow
from outwarp.tui.tokens import BAD, DIM, WARN

log = logging.getLogger(__name__)


def _style_for_line(line: str) -> str:
    upper = line[:60].upper()
    if "[ERROR]" in upper or "ERROR " in upper or "[CRITICAL]" in upper:
        return f"[{BAD}]{line}[/]"
    if "[WARN" in upper or "WARN " in upper:
        return f"[{WARN}]{line}[/]"
    if "[INFO]" in upper:
        return f"[#f4f5f7]{line}[/]"
    return f"[{DIM}]{line}[/]"


class LiveLog(RichLog):
    """RichLog that tails a file via `outwarp.logs.tail_follow` on mount."""

    def __init__(self, path: Path, *, max_lines: int = 5000, **kwargs) -> None:
        super().__init__(
            id="log", highlight=False, markup=True, max_lines=max_lines, **kwargs,
        )
        self._path = path
        self._task: asyncio.Task | None = None

    def on_mount(self) -> None:
        self._task = asyncio.create_task(self._follow(), name="live-log-tail")

    def on_unmount(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _follow(self) -> None:
        try:
            async for line in tail_follow(self._path, poll_interval=0.3):
                self.write(_style_for_line(line))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("LiveLog tail failed")
