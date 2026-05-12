from __future__ import annotations

import asyncio
import logging
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Callable

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from warpsocket.config import ClientConfig, ConfigError, import_warpcfg
from warpsocket.logs import MemoryLogHandler
from warpsocket.tunnel import TunnelManager, TunnelState

log = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent / "ui"
_LOG_POLL_SECONDS = 0.25

ManagerRef = list  # list[TunnelManager | None]; mutable so the orchestrator can swap.
ImportCallback = Callable[[ClientConfig], None]


class _TokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject any request that doesn't carry the session token.

    HTTP requests use ``Authorization: Bearer <token>``; the initial HTML load
    and WebSocket upgrades use ``?token=<token>`` because browsers can't set
    a header on a plain navigation or on a WebSocket constructor.
    """

    def __init__(self, app: FastAPI, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        # WebSocket upgrades have their own auth check; let them through here.
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        provided = _extract_token(request)
        if not provided or not secrets.compare_digest(provided, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
        response = await call_next(request)
        # On the first navigation (?token=X) plant a same-origin cookie so static
        # assets requested by the page can authenticate without query rewriting.
        if request.query_params.get("token") and _COOKIE_NAME not in request.cookies:
            response.set_cookie(
                _COOKIE_NAME,
                self._token,
                httponly=False,  # JS reads it to call WebSocket with ?token=
                samesite="strict",
            )
        return response


_COOKIE_NAME = "warpsocket_token"


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    qs = request.query_params.get("token")
    if qs:
        return qs
    return request.cookies.get(_COOKIE_NAME)


def _require_ws_token(token: str):
    async def dep(ws: WebSocket) -> None:
        provided = ws.query_params.get("token")
        if not provided or not secrets.compare_digest(provided, token):
            await ws.close(code=4401)
            raise HTTPException(status_code=401)
    return dep


def _state_payload(manager: TunnelManager | None) -> dict:
    if manager is None:
        return {
            "state": "no_config",
            "config_present": False,
            "server_endpoint": None,
        }
    cfg = manager.config
    return {
        "state": manager.state.value,
        "config_present": True,
        "server_endpoint": f"{cfg.server.endpoint}:{cfg.server.port}",
        "tunnel_name": cfg.wireguard.tunnel_name,
    }


def create_app(
    manager_ref: ManagerRef,
    memory_handler: MemoryLogHandler,
    on_import: ImportCallback,
    token: str,
    *,
    ui_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI app for the client.

    ``manager_ref`` is a single-element list holding the current TunnelManager
    (or None when there's no config). The orchestrator swaps the element in
    place when a new .warpcfg is imported — endpoints always read index 0.
    """
    app = FastAPI(title="WarpSocket Client", version="1")
    app.add_middleware(_TokenAuthMiddleware, token=token)

    ws_auth = _require_ws_token(token)

    @app.get("/api/status")
    def get_status() -> dict:
        return _state_payload(manager_ref[0])

    @app.post("/api/connect", status_code=status.HTTP_202_ACCEPTED)
    def post_connect() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="no config imported")
        m.start()
        return {"ok": True}

    @app.post("/api/disconnect", status_code=status.HTTP_202_ACCEPTED)
    def post_disconnect() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="no config imported")
        threading.Thread(target=m.stop, daemon=True, name="api-disconnect").start()
        return {"ok": True}

    @app.post("/api/reconnect", status_code=status.HTTP_202_ACCEPTED)
    def post_reconnect() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="no config imported")
        def _restart() -> None:
            m.stop()
            m.start()
        threading.Thread(target=_restart, daemon=True, name="api-reconnect").start()
        return {"ok": True}

    @app.get("/api/config")
    def get_config() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=404, detail="no config imported")
        return m.config.to_dict()

    @app.post("/api/import-config")
    async def post_import_config(file: UploadFile = File(...)) -> dict:
        data = await file.read()
        tmp = tempfile.NamedTemporaryFile(
            prefix="warpsocket-import-", suffix=".warpcfg", delete=False
        )
        try:
            tmp.write(data)
            tmp.close()
            try:
                cfg = import_warpcfg(Path(tmp.name))
            except ConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass

        on_import(cfg)
        return {"ok": True, "config": cfg.to_dict()}

    @app.websocket("/api/ws/logs")
    async def ws_logs(websocket: WebSocket, _: None = Depends(ws_auth)) -> None:
        await websocket.accept()
        sent = 0
        try:
            while True:
                snapshot = memory_handler.snapshot()
                if len(snapshot) < sent:
                    # Buffer rotated; resend everything.
                    sent = 0
                if len(snapshot) > sent:
                    new = snapshot[sent:]
                    sent = len(snapshot)
                    for line in new:
                        await websocket.send_json({"line": line})
                await asyncio.sleep(_LOG_POLL_SECONDS)
        except WebSocketDisconnect:
            return
        except Exception:
            log.exception("ws_logs raised")

    if ui_dir is None:
        ui_dir = _UI_DIR
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app
