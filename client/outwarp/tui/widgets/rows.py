"""One-line "label  value" rows shared by the dashboard cards."""

from __future__ import annotations

from outwarp.i18n import cell_width, pad
from outwarp.tui.tokens import DIM


def label_width(labels: list[str]) -> int:
    """Terminal cells of the longest label, plus two of air."""
    return max((cell_width(label) for label in labels), default=0) + 2


def kv(label: str, value: str, width: int) -> str:
    """`label` dimmed and padded to `width` cells, then `value` (Rich markup)."""
    return f"[{DIM}]{pad(label, width)}[/]{value}"
