from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from outwarp.logs import tail_follow


@pytest.mark.asyncio
async def test_tail_follow_emits_appended_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_text("", encoding="utf-8")

    seen: list[str] = []

    async def consume() -> None:
        async for line in tail_follow(path, poll_interval=0.02):
            seen.append(line)
            if len(seen) >= 3:
                return

    async def producer() -> None:
        await asyncio.sleep(0.05)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("first\nsecond\n")
            fh.flush()
        await asyncio.sleep(0.05)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("third\n")
            fh.flush()

    await asyncio.wait_for(
        asyncio.gather(consume(), producer()), timeout=2.0
    )
    assert seen == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_tail_follow_recovers_after_rotation(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_text("initial\n", encoding="utf-8")

    seen: list[str] = []

    async def consume() -> None:
        async for line in tail_follow(path, poll_interval=0.02):
            seen.append(line)
            if "after-rotate" in line:
                return

    async def rotator() -> None:
        await asyncio.sleep(0.05)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("pre-rotate\n")
        await asyncio.sleep(0.05)
        # Simulate rotation: delete and rewrite — inode changes.
        os.remove(path)
        await asyncio.sleep(0.05)
        path.write_text("after-rotate\n", encoding="utf-8")

    await asyncio.wait_for(asyncio.gather(consume(), rotator()), timeout=2.0)
    assert "pre-rotate" in seen
    assert "after-rotate" in seen


@pytest.mark.asyncio
async def test_tail_follow_from_start_yields_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_text("line1\nline2\n", encoding="utf-8")
    seen: list[str] = []

    async def consume() -> None:
        async for line in tail_follow(path, poll_interval=0.02, from_start=True):
            seen.append(line)
            if len(seen) >= 2:
                return

    await asyncio.wait_for(consume(), timeout=1.0)
    assert seen[:2] == ["line1", "line2"]
