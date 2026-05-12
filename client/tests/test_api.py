from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from warpsocket.api import create_app
from warpsocket.logs import MemoryLogHandler
from warpsocket.tunnel import TunnelState

_VALID_WARPCFG = {
    "schema_version": 1,
    "server": {
        "endpoint": "203.0.113.42",
        "port": 443,
        "http_upgrade_path_prefix": "s3cret",
    },
    "tls": {
        "cert_fingerprint_sha256":
            "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89"
            ":AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89",
    },
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "WarpSocket",
        "client_address": "10.0.0.42/32",
        "client_private_key": "dGVzdGtleQ==",
        "server_public_key": "c2VydmVya2V5",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
}

TOKEN = "test-token-xyz"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _make_app(manager=None, *, on_import=None, tmp_path: Path | None = None):
    handler = MemoryLogHandler()
    ref = [manager]
    captured = {"cfg": None}

    def default_on_import(cfg):
        captured["cfg"] = cfg

    app = create_app(
        ref,
        handler,
        on_import or default_on_import,
        TOKEN,
        ui_dir=tmp_path,
    )
    return app, ref, handler, captured


def test_status_requires_token():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_status_with_bearer():
    app, *_ = _make_app()
    c = TestClient(app)
    r = c.get("/api/status", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"state": "no_config", "config_present": False, "server_endpoint": None}


def test_status_with_query_param_sets_cookie():
    app, *_ = _make_app()
    c = TestClient(app)
    r = c.get(f"/api/status?token={TOKEN}")
    assert r.status_code == 200
    assert "warpsocket_token" in r.cookies


def test_status_with_manager():
    mgr = MagicMock()
    mgr.state = TunnelState.CONNECTED
    mgr.config.server.endpoint = "1.2.3.4"
    mgr.config.server.port = 443
    mgr.config.wireguard.tunnel_name = "WG"
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.get("/api/status", headers=AUTH)
    body = r.json()
    assert body["state"] == "connected"
    assert body["config_present"] is True
    assert body["server_endpoint"] == "1.2.3.4:443"
    assert body["tunnel_name"] == "WG"


def test_connect_without_manager_returns_409():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.post("/api/connect", headers=AUTH).status_code == 409


def test_connect_invokes_manager_start():
    mgr = MagicMock()
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.post("/api/connect", headers=AUTH)
    assert r.status_code == 202
    mgr.start.assert_called_once()


def test_disconnect_spawns_thread_calling_stop():
    mgr = MagicMock()
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    assert c.post("/api/disconnect", headers=AUTH).status_code == 202
    # The endpoint dispatches to a daemon thread; give it a moment.
    import time
    for _ in range(50):
        if mgr.stop.called:
            break
        time.sleep(0.01)
    mgr.stop.assert_called_once()


def test_get_config_when_unconfigured():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.get("/api/config", headers=AUTH).status_code == 404


def test_get_config_when_configured():
    mgr = MagicMock()
    mgr.config.to_dict.return_value = {"hello": "world"}
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.get("/api/config", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_import_config_success_invokes_callback(tmp_path):
    captured = {"cfg": None}

    def on_import(cfg):
        captured["cfg"] = cfg

    app, ref, _, _ = _make_app(on_import=on_import)
    c = TestClient(app)
    payload = json.dumps(_VALID_WARPCFG).encode("utf-8")
    r = c.post(
        "/api/import-config",
        files={"file": ("test.warpcfg", payload, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["config"]["server"]["endpoint"] == "203.0.113.42"
    assert captured["cfg"] is not None
    assert captured["cfg"].server.endpoint == "203.0.113.42"


def test_import_config_invalid_returns_400():
    app, *_ = _make_app()
    c = TestClient(app)
    bad = b"{ not even json"
    r = c.post(
        "/api/import-config",
        files={"file": ("bad.warpcfg", bad, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 400
    assert "error" in r.json()


def test_ws_logs_streams_snapshot_then_new_lines():
    app, _, handler, _ = _make_app()
    handler._buf.append("first")
    handler._buf.append("second")

    c = TestClient(app)
    with c.websocket_connect(f"/api/ws/logs?token={TOKEN}") as ws:
        assert ws.receive_json() == {"line": "first"}
        assert ws.receive_json() == {"line": "second"}
        handler._buf.append("third")
        assert ws.receive_json() == {"line": "third"}


def test_ws_logs_rejects_bad_token():
    from starlette.websockets import WebSocketDisconnect
    app, *_ = _make_app()
    c = TestClient(app)
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/ws/logs?token=wrong"):
        pass


def test_static_ui_is_served_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    app, *_ = _make_app(tmp_path=tmp_path)
    c = TestClient(app)
    r = c.get(f"/?token={TOKEN}")
    assert r.status_code == 200
    assert "<html>hi</html>" in r.text
