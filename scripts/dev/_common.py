"""Shared bits for the dev screenshot harnesses (not shipped, not tested in CI)."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def launch_chromium(p):
    """Chromium from Playwright; ``OUTWARP_CHROMIUM`` overrides the binary.

    In the Claude Code cloud sandbox Playwright's own version may not match the
    pre-installed browsers: set ``OUTWARP_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome``.
    """
    exe = os.environ.get("OUTWARP_CHROMIUM")
    return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
