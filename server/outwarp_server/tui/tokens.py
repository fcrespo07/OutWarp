"""Canonical color tokens for the server TUI.

Single source of truth for the hex values used in Rich console markup (e.g.
``f"[{BAD}]...[/]"``). They mirror the design tokens in ``ui/styles.css`` so the
TUI and the pywebview GUI render the same colour for the same concept. The TCSS
variables in ``styles.tcss`` carry the same values for stylesheet-driven widgets;
keep all three in sync when the palette changes.
"""

from __future__ import annotations

BRAND = "#2563ff"
OK = "#2ee0b3"
WARN = "#ff8a3d"
BAD = "#ff4d6d"
DIM = "#6e747e"
