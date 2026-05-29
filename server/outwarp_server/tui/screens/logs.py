from __future__ import annotations

import logging
import shutil
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog

log = logging.getLogger(__name__)


class LogsScreen(Screen):
    """Tail journald (wstunnel-outwarp.service) when available."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", priority=True),
        Binding("q", "app.quit", "Quit", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield RichLog(id="log", highlight=False, markup=False, max_lines=5000)
        yield Footer()

    def on_mount(self) -> None:
        self._proc: subprocess.Popen | None = None
        if shutil.which("journalctl") is None:
            self.query_one(RichLog).write("journalctl not available on this host.")
            return
        self._proc = subprocess.Popen(
            ["journalctl", "-u", "wstunnel-outwarp.service", "-f", "-n", "200", "--no-pager"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.set_interval(0.25, self._drain)

    def _drain(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        # Non-blocking read of whatever's available.
        try:
            import os
            import select
            fd = proc.stdout.fileno()
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                return
            data = os.read(fd, 65536).decode("utf-8", errors="replace")
        except Exception:
            return
        if not data:
            return
        log_widget = self.query_one(RichLog)
        for line in data.splitlines():
            log_widget.write(line)

    def on_unmount(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
