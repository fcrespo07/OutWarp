from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.app import App

from outwarp.tui.screens.logs import LogsScreen


class _Host(App):
    def on_mount(self) -> None:
        self.push_screen(LogsScreen())


async def _fake_tail(path, poll_interval=0.3):
    for line in ("2026-10-01 10:00:00 [INFO] up", "2026-10-01 10:00:01 [ERROR] boom"):
        yield line


@pytest.mark.asyncio
async def test_export_saves_the_filtered_lines_and_clear_empties_the_view(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr("outwarp.tui.screens.logs.tail_follow", _fake_tail)
    monkeypatch.chdir(tmp_path)
    app = _Host()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("e", "x")
        await pilot.pause()
        files = list(tmp_path.glob("outwarp-logs-*.txt"))
        assert len(files) == 1
        assert files[0].read_text().strip().endswith("[ERROR] boom")
        assert "[INFO]" not in files[0].read_text()
        await pilot.press("c")
        await pilot.pause()
        assert app.screen._all_lines == []
