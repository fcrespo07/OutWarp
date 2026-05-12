from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from warpsocket_server.config import (
    ConfigError,
    ServerConfig,
    default_config_dir,
    default_config_path,
)
from warpsocket_server.crypto import generate_tls_cert, generate_wg_keypair
from warpsocket_server.logs import MemoryLogHandler
from warpsocket_server.server_manager import ServerManager, ServerState
from warpsocket_server.wireguard import get_live_peers

log = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent / "ui"
_LOG_POLL_SECONDS = 0.25
_ONLINE_WINDOW_SECONDS = 180
_COOKIE_NAME = "warpsocket_server_token"

ManagerRef = list  # list[ServerManager | None]
SetupCallback = Callable[[ServerConfig, ServerManager], None]


class _TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        provided = _extract_token(request)
        if not provided or not secrets.compare_digest(provided, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
        response = await call_next(request)
        if request.query_params.get("token") and _COOKIE_NAME not in request.cookies:
            response.set_cookie(_COOKIE_NAME, self._token, httponly=False, samesite="strict")
        return response


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


def _status_payload(manager: ServerManager | None) -> dict:
    if manager is None:
        return {"state": "no_config", "config_present": False}
    cfg = manager.config
    return {
        "state": manager.state.value,
        "config_present": True,
        "endpoint": cfg.endpoint,
        "port": cfg.port,
        "subnet": cfg.subnet,
        "server_address": cfg.server_address,
        "wg_listen_port": cfg.wg_listen_port,
        "cert_fingerprint_sha256": cfg.cert_fingerprint_sha256,
        "clients_count": len(cfg.clients),
    }


def _peer_status(latest_handshake: int | None, now: int) -> tuple[str, int | None]:
    if latest_handshake is None:
        return "idle", None
    age = now - latest_handshake
    return ("online" if age < _ONLINE_WINDOW_SECONDS else "offline", age)


def create_app(
    manager_ref: ManagerRef,
    memory_handler: MemoryLogHandler,
    on_setup_complete: SetupCallback,
    token: str,
    *,
    ui_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI app for the server.

    Same token middleware pattern as the client. ``on_setup_complete`` is
    called after the /api/setup wizard finishes; it receives a fresh
    ServerConfig and a brand-new ServerManager so the orchestrator can wire
    them into the tray.
    """
    app = FastAPI(title="WarpSocket Server", version="1")
    app.add_middleware(_TokenAuthMiddleware, token=token)

    ws_auth = _require_ws_token(token)

    @app.get("/api/status")
    def get_status() -> dict:
        return _status_payload(manager_ref[0])

    @app.get("/api/deps")
    def get_deps() -> dict:
        return {"wstunnel": shutil.which("wstunnel"), "wg": shutil.which("wg")}

    @app.get("/api/detect-ip")
    def detect_ip() -> dict:
        try:
            with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
                return {"ip": r.read().decode().strip()}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"ip": None, "error": str(exc)}

    @app.post("/api/start", status_code=status.HTTP_202_ACCEPTED)
    def post_start() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        m.start()
        return {"ok": True}

    @app.post("/api/stop", status_code=status.HTTP_202_ACCEPTED)
    def post_stop() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        threading.Thread(target=m.stop, daemon=True, name="api-stop").start()
        return {"ok": True}

    @app.post("/api/restart", status_code=status.HTTP_202_ACCEPTED)
    def post_restart() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        threading.Thread(target=m.restart, daemon=True, name="api-restart").start()
        return {"ok": True}

    @app.get("/api/clients")
    def list_clients() -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        try:
            live = get_live_peers()
        except Exception:
            live = {}
        now = int(time.time())
        out = []
        for c in m.config.clients:
            peer = live.get(c.public_key)
            if peer is None:
                status_, age = "unknown", None
                endpoint = None
                rx = tx = 0
            else:
                status_, age = _peer_status(peer.latest_handshake, now)
                endpoint = peer.endpoint
                rx, tx = peer.transfer_rx, peer.transfer_tx
            out.append({
                "name": c.name,
                "address": c.address,
                "public_key": c.public_key,
                "status": status_,
                "last_handshake_seconds_ago": age,
                "endpoint": endpoint,
                "rx_bytes": rx,
                "tx_bytes": tx,
            })
        return {"clients": out}

    @app.post("/api/clients", status_code=status.HTTP_201_CREATED)
    def add_client(payload: dict = Body(...)) -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            warpcfg_path = m.add_client(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        warpcfg_bytes = warpcfg_path.read_bytes()
        return {
            "name": name,
            "path": str(warpcfg_path),
            "warpcfg_base64": base64.b64encode(warpcfg_bytes).decode("ascii"),
        }

    @app.delete("/api/clients/{name}")
    def revoke_client(name: str) -> dict:
        m = manager_ref[0]
        if m is None:
            raise HTTPException(status_code=409, detail="server not configured")
        try:
            m.revoke_client(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/setup")
    def post_setup(payload: dict = Body(...)) -> dict:
        if manager_ref[0] is not None:
            raise HTTPException(status_code=409, detail="server already configured")

        endpoint = (payload.get("endpoint") or "").strip()
        if not endpoint:
            raise HTTPException(status_code=400, detail="endpoint is required")
        try:
            port = int(payload.get("port", 443))
            wg_listen_port = int(payload.get("wg_listen_port", 51820))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid port") from exc
        for n, v in (("port", port), ("wg_listen_port", wg_listen_port)):
            if not (1 <= v <= 65535):
                raise HTTPException(status_code=400, detail=f"{n} out of range")
        subnet = (payload.get("subnet") or "10.0.0.0/24").strip()
        server_address = (
            payload.get("server_address")
            or f"{subnet.split('/')[0].rsplit('.', 1)[0]}.1/24"
        ).strip()

        cfg_dir = default_config_dir()
        try:
            upgrade_path = secrets.token_urlsafe(32)
            cert_path, key_path, fingerprint = generate_tls_cert(endpoint, cfg_dir / "tls")
            wg_bin = shutil.which("wg")
            wg_priv, wg_pub = generate_wg_keypair(Path(wg_bin) if wg_bin else None)
        except Exception as exc:
            log.exception("setup: crypto generation failed")
            raise HTTPException(status_code=500, detail=f"crypto: {exc}") from exc

        new_config = ServerConfig(
            schema_version=1,
            endpoint=endpoint,
            port=port,
            http_upgrade_path_prefix=upgrade_path,
            cert_path=str(cert_path),
            key_path=str(key_path),
            cert_fingerprint_sha256=fingerprint,
            wg_private_key=wg_priv,
            wg_public_key=wg_pub,
            subnet=subnet,
            server_address=server_address,
            wg_listen_port=wg_listen_port,
            clients=[],
        )
        try:
            new_config.save(default_config_path())
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"save config: {exc}") from exc

        new_manager = ServerManager(new_config)
        on_setup_complete(new_config, new_manager)
        return {"ok": True, "fingerprint": fingerprint}

    @app.websocket("/api/ws/logs")
    async def ws_logs(websocket: WebSocket, _: None = Depends(ws_auth)) -> None:
        await websocket.accept()
        sent = 0
        try:
            while True:
                snapshot = memory_handler.snapshot()
                if len(snapshot) < sent:
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
