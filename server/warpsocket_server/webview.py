from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI

log = logging.getLogger(__name__)


@dataclass
class WebviewSession:
    port: int
    token: str
    url: str
    _server: object
    _server_thread: threading.Thread
    _window: object | None = None
    _on_close: Callable[[], None] | None = None

    def run(self, title: str = "WarpSocket Server") -> None:
        import webview as pywebview

        self._window = pywebview.create_window(
            title, self.url, width=1000, height=680, resizable=True
        )

        def _on_closed() -> None:
            log.debug("pywebview window closed")
            if self._on_close is not None:
                try:
                    self._on_close()
                except Exception:
                    log.exception("on_close handler raised")

        self._window.events.closed += _on_closed
        try:
            pywebview.start()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        srv = getattr(self, "_server", None)
        if srv is not None and not getattr(srv, "should_exit", False):
            srv.should_exit = True
        if self._server_thread.is_alive():
            self._server_thread.join(timeout=5)


def _wait_until_listening(port: int, timeout: float = 10.0) -> None:
    import socket as _socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"uvicorn did not start listening on 127.0.0.1:{port}")


def start(
    app: FastAPI,
    port: int,
    token: str,
    *,
    log_level: str = "warning",
    on_close: Callable[[], None] | None = None,
) -> WebviewSession:
    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level=log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name=f"uvicorn-{port}")
    thread.start()
    _wait_until_listening(port)
    log.info("Uvicorn listening on 127.0.0.1:%d", port)

    return WebviewSession(
        port=port,
        token=token,
        url=f"http://127.0.0.1:{port}/?token={token}",
        _server=server,
        _server_thread=thread,
        _on_close=on_close,
    )


def show_window() -> None:
    try:
        import webview as pywebview
    except ImportError:
        return
    if pywebview.windows:
        win = pywebview.windows[0]
        try:
            win.show()
            win.restore()
        except Exception:
            log.exception("Could not show webview window")


def static_ui_dir(package_dir: Path) -> Path:
    return package_dir / "ui"
