"""Non-blocking desktop notifications for Linux.

Sends a notification via ``notify-send`` (libnotify) in a background thread so
the caller never blocks. Silently no-ops on non-Linux platforms or when
``notify-send`` is not installed (e.g. headless servers).
"""
from __future__ import annotations

import subprocess
import sys
import threading

_APP_NAME = "OutWarp"


def _icon() -> object:
    """Absolute path to the bundled PNG: works whether or not the hicolor
    icon was installed, and mako/omarchy-shell/dunst all take a path."""
    from outwarp.desktop_linux import icon_path

    return icon_path()


def notify(
    title: str,
    body: str = "",
    *,
    urgency: str = "normal",
) -> None:
    """Fire a desktop notification. Non-blocking, best-effort, Linux-only.

    ``urgency`` is one of ``low``, ``normal`` (default), or ``critical``.
    """
    if sys.platform != "linux":
        return

    def _do() -> None:
        import contextlib
        with contextlib.suppress(FileNotFoundError, OSError):
            subprocess.Popen(
                ["notify-send", "-a", _APP_NAME, "-i", str(_icon()), "-u", urgency,
                 "--", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    threading.Thread(target=_do, daemon=True, name="outwarp-notify").start()
