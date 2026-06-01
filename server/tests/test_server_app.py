"""Smoke tests for ``outwarp_server.server_app.main`` — the pywebview entry-point.

Most of the function only matters when the GTK/WebKit stack is actually loaded
(macOS / Windows installs, or Linux + `OUTWARP_SERVER_GUI=1`). On Linux the
relevant path is the early fallback that hands control to the Textual TUI when
the pywebview marker excluded the dependency from the wheel.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only TUI fallback path")
def test_linux_redirects_to_tui_when_webview_missing() -> None:
    """The server has the same Linux-default redirect as the client: ``server
    pyproject`` carries ``pywebview>=5.0 ; sys_platform != 'linux'`` on the
    ``gui`` extra, so a vanilla install.sh run never installs pywebview. The
    GUI entry-point must notice and delegate to ``outwarp-server tui``."""
    from outwarp_server import server_app

    # `webview = None` makes the `import webview` statement raise ImportError
    # via Python's import system (a None entry in sys.modules is the
    # well-defined way to say "this import will fail").
    with (
        patch.dict(sys.modules, {"webview": None}),
        patch("outwarp_server.cli.main", return_value=0) as fake_cli,
    ):
        assert server_app.main() == 0
        fake_cli.assert_called_once_with(["tui"])
