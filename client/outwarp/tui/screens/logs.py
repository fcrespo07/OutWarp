from __future__ import annotations

import asyncio
import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static

from outwarp.logs import default_log_path, tail_follow
from outwarp.tui.tokens import BAD, DIM, WARN


def _style_line(line: str) -> str:
    upper = line[:60].upper()
    if "[ERROR]" in upper or "ERROR " in upper or "[CRITICAL]" in upper:
        return f"[{BAD}]{line}[/]"
    if "[WARN" in upper or "WARN " in upper:
        return f"[{WARN}]{line}[/]"
    if "[INFO]" in upper:
        return f"[#f4f5f7]{line}[/]"
    return f"[{DIM}]{line}[/]"


def _passes_level(line: str, level: str | None) -> bool:
    if level is None:
        return True
    upper = line[:60].upper()
    if level == "e":
        return "[ERROR]" in upper or "ERROR " in upper or "[CRITICAL]" in upper
    if level == "w":
        return (
            "[WARN" in upper or "WARN " in upper
            or "[ERROR]" in upper or "ERROR " in upper
            or "[CRITICAL]" in upper
        )
    return True


class LogsScreen(Screen):
    """Full-screen log tail with search, level filters, and pause."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("g", "scroll_home", "Top"),
        Binding("G", "scroll_end", "Bottom", show=True, key_display="G"),
        Binding("q", "app.quit", "Quit", priority=True),
        Binding("slash", "toggle_search", "Search"),
        Binding("e", "toggle_errors", "Errors"),
        Binding("w", "toggle_warnings", "Warnings+"),
        Binding("p", "toggle_pause", "Pause"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="root"):
            yield Input(placeholder="filter text...", id="search")
            yield RichLog(
                id="log", highlight=False, markup=True, max_lines=5000,
            )
            yield Static("", id="filter-bar")
        yield Footer()

    def on_mount(self) -> None:
        # Hide the search input by default.
        self.query_one("#search", Input).display = False
        self._all_lines: list[str] = []
        self._paused = False
        self._search = ""
        self._level: str | None = None
        self._task: asyncio.Task | None = asyncio.create_task(
            self._follow(), name="logs-tail",
        )

    def on_unmount(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _follow(self) -> None:
        try:
            async for line in tail_follow(default_log_path(), poll_interval=0.3):
                self._all_lines.append(line)
                if not self._paused and self._line_visible(line):
                    with contextlib.suppress(Exception):
                        self.query_one("#log", RichLog).write(
                            _style_line(line), markup=True,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _line_visible(self, line: str) -> bool:
        if not _passes_level(line, self._level):
            return False
        return not self._search or self._search.lower() in line.lower()

    def _redraw(self) -> None:
        log_widget = self.query_one("#log", RichLog)
        log_widget.clear()
        for line in self._all_lines:
            if self._line_visible(line):
                log_widget.write(_style_line(line), markup=True)
        with contextlib.suppress(Exception):
            log_widget.scroll_end(animate=False)
        self._update_filter_bar()

    def _update_filter_bar(self) -> None:
        parts: list[str] = []
        if self._paused:
            parts.append(f"[{WARN}]PAUSED[/]")
        if self._level == "e":
            parts.append(f"[{BAD}]errors only[/]")
        elif self._level == "w":
            parts.append(f"[{WARN}]warnings+[/]")
        if self._search:
            parts.append(f"[{DIM}]search: {self._search}[/]")
        bar = "  ".join(parts)
        with contextlib.suppress(Exception):
            self.query_one("#filter-bar", Static).update(bar)

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_back(self) -> None:
        search_input = self.query_one("#search", Input)
        if search_input.display:
            search_input.display = False
            search_input.value = ""
            self._search = ""
            self._redraw()
            return
        with contextlib.suppress(Exception):
            self.app.pop_screen()

    def action_toggle_search(self) -> None:
        search_input = self.query_one("#search", Input)
        if search_input.display:
            search_input.display = False
            search_input.value = ""
            self._search = ""
            self._redraw()
        else:
            search_input.display = True
            search_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._search = event.value.strip()
            self._redraw()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#log", RichLog).focus()

    def action_toggle_errors(self) -> None:
        self._level = None if self._level == "e" else "e"
        self._redraw()

    def action_toggle_warnings(self) -> None:
        self._level = None if self._level == "w" else "w"
        self._redraw()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self._update_filter_bar()
        if not self._paused:
            # Resume: scroll to bottom.
            with contextlib.suppress(Exception):
                self.query_one("#log", RichLog).scroll_end(animate=False)

    def action_scroll_home(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#log", RichLog).scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#log", RichLog).scroll_end(animate=False)
