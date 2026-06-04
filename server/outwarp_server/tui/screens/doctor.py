from __future__ import annotations

import asyncio
import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from outwarp_server.diagnostics import CheckResult, Status, run_all
from outwarp_server.tui.tokens import BAD, BRAND, DIM, OK, WARN

log = logging.getLogger(__name__)

_ICON = {
    Status.PASS: f"[{OK}]✓[/]",
    Status.WARN: f"[{WARN}]⚠[/]",
    Status.FAIL: f"[{BAD}]✗[/]",
    Status.SKIP: f"[{DIM}]—[/]",
}


class DoctorScreen(Screen):
    BINDINGS = [
        Binding("r", "rerun", "Re-run"),
        Binding("f", "apply_fix", "Apply fix"),
        Binding("escape", "app.pop_screen", "Back", priority=True),
        Binding("q", "app.quit", "Quit", priority=True),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._results: list[CheckResult] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="table", cursor_type="row")
        yield Static("Running checks...", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns(" ", "Check", "Detail")
        t.focus()
        self.query_one("#detail", Static).update(f"[{DIM}]Running checks...[/]")
        asyncio.create_task(self._run_async(), name="doctor-run")

    def action_rerun(self) -> None:
        # Re-run in a worker so the UI thread keeps draining keys (escape, q).
        asyncio.create_task(self._run_async(), name="doctor-rerun")

    async def _run_async(self) -> None:
        loop = asyncio.get_running_loop()
        config = self.app.config
        try:
            results = await loop.run_in_executor(None, lambda: run_all(config))
        except Exception as exc:
            log.exception("Doctor run failed")
            results = [CheckResult("doctor", Status.FAIL, detail=str(exc))]
        self._results = results
        self._redraw()

    def _redraw(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for r in self._results:
            table.add_row(_ICON[r.status], r.name, (r.detail or "")[:80])
        self._update_detail()

    def on_data_table_row_highlighted(self, event) -> None:
        self._update_detail()

    def _update_detail(self) -> None:
        table = self.query_one(DataTable)
        idx = table.cursor_row
        if idx is None or idx < 0 or idx >= len(self._results):
            self.query_one("#detail", Static).update("")
            return
        r = self._results[idx]
        parts = [f"[bold]{r.name}[/bold]  {_ICON[r.status]}", r.detail or ""]
        if r.remediation:
            parts.append(f"[{DIM}]→[/] {r.remediation}")
        if r.remediation_command:
            parts.append(f"[{BRAND}]$[/] {r.remediation_command}")
        if r.fix_kind:
            parts.append(f"[{DIM}]fix:[/] {r.fix_kind}")
        self.query_one("#detail", Static).update("\n".join(parts))

    def action_apply_fix(self) -> None:
        table = self.query_one(DataTable)
        idx = table.cursor_row
        if idx is None or idx < 0 or idx >= len(self._results):
            return
        r = self._results[idx]
        if r.fix_kind != "auto" or r.fix_callable is None:
            self.notify(
                f"Fix is {r.fix_kind or 'unavailable'} — copy the command and run it manually.",
                severity="warning",
            )
            return

        from outwarp_server.tui.modals.confirm import ConfirmModal

        def _go(result: bool | None) -> None:
            if not result:
                return
            try:
                r.fix_callable(self.app.config)
            except Exception as exc:
                self.notify(f"Fix failed: {exc}", severity="error")
                return
            self.notify("Fix applied. Re-running checks...", severity="information")
            self.action_rerun()

        self.app.push_screen(
            ConfirmModal(
                title=f"Apply fix for '{r.name}'?",
                body=r.remediation or "Run the recommended action.",
                ok_label="Apply",
            ),
            _go,
        )

    def action_help(self) -> None:
        from outwarp_server.tui.modals.help import HelpModal
        self.app.push_screen(HelpModal())
