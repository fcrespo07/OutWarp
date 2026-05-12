from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from warpsocket_server.api import create_app
from warpsocket_server.config import ClientEntry, ServerConfig
from warpsocket_server.logs import MemoryLogHandler
from warpsocket_server.server_manager import ServerState

TOKEN = "stoken-xyz"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _make_config(clients=()) -> ServerConfig:
    return ServerConfig(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="secret",
        cert_path="/etc/warpsocket/tls/cert.pem",
        key_path="/etc/warpsocket/tls/key.pem",
        cert_fingerprint_sha256="AB" + ":AB" * 31,
        wg_private_key="priv",
        wg_public_key="pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=list(clients),
    )


def _make_manager(state=ServerState.STOPPED, clients=()) -> MagicMock:
    m = MagicMock()
    m.state = state
    m.config = _make_config(clients=clients)
    return m


def _make_app(manager=None, *, ui_dir: Path | None = None, on_setup=None):
    handler = MemoryLogHandler()
    ref = [manager]
    cb = on_setup or (lambda cfg, mgr: None)
    app = create_app(ref, handler, cb, TOKEN, ui_dir=ui_dir)
    return app, ref, handler


def test_status_requires_token():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.get("/api/status").status_code == 401


def test_status_unconfigured():
    app, *_ = _make_app()
    c = TestClient(app)
    r = c.get("/api/status", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"state": "no_config", "config_present": False}


def test_status_configured():
    mgr = _make_manager(state=ServerState.RUNNING)
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    body = c.get("/api/status", headers=AUTH).json()
    assert body["state"] == "running"
    assert body["config_present"] is True
    assert body["endpoint"] == "203.0.113.42"
    assert body["port"] == 443
    assert body["clients_count"] == 0


def test_deps_uses_shutil_which():
    app, *_ = _make_app()
    c = TestClient(app)
    with patch("warpsocket_server.api.shutil.which", side_effect=lambda b: f"/usr/bin/{b}"):
        r = c.get("/api/deps", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"wstunnel": "/usr/bin/wstunnel", "wg": "/usr/bin/wg"}


def test_start_without_manager_409():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.post("/api/start", headers=AUTH).status_code == 409


def test_start_invokes_manager():
    mgr = _make_manager()
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.post("/api/start", headers=AUTH)
    assert r.status_code == 202
    mgr.start.assert_called_once()


def test_clients_list_merges_live_state():
    clients = [
        ClientEntry(name="alice", public_key="aliceKey", address="10.0.0.2/32"),
        ClientEntry(name="bob", public_key="bobKey", address="10.0.0.3/32"),
    ]
    mgr = _make_manager(state=ServerState.RUNNING, clients=clients)
    app, *_ = _make_app(mgr)

    fake_peer_alice = MagicMock(
        endpoint="1.2.3.4:5", latest_handshake=10_000, transfer_rx=100, transfer_tx=200
    )

    with (
        patch("warpsocket_server.api.get_live_peers", return_value={"aliceKey": fake_peer_alice}),
        patch("warpsocket_server.api.time.time", return_value=10_010),
    ):
        c = TestClient(app)
        r = c.get("/api/clients", headers=AUTH)

    assert r.status_code == 200
    data = r.json()["clients"]
    by_name = {c["name"]: c for c in data}
    assert by_name["alice"]["status"] == "online"
    assert by_name["alice"]["last_handshake_seconds_ago"] == 10
    assert by_name["alice"]["rx_bytes"] == 100
    assert by_name["bob"]["status"] == "unknown"
    assert by_name["bob"]["endpoint"] is None


def test_add_client_returns_base64_warpcfg(tmp_path):
    warpcfg_file = tmp_path / "alice.warpcfg"
    warpcfg_file.write_bytes(b"FAKE_WARPCFG_BYTES")

    mgr = _make_manager()
    mgr.add_client.return_value = warpcfg_file

    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.post("/api/clients", json={"name": "alice"}, headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "alice"
    assert data["path"] == str(warpcfg_file)
    assert base64.b64decode(data["warpcfg_base64"]) == b"FAKE_WARPCFG_BYTES"
    mgr.add_client.assert_called_once_with("alice")


def test_add_client_rejects_empty_name():
    app, *_ = _make_app(_make_manager())
    c = TestClient(app)
    assert c.post("/api/clients", json={"name": "  "}, headers=AUTH).status_code == 400


def test_add_client_propagates_value_error():
    mgr = _make_manager()
    mgr.add_client.side_effect = ValueError("duplicate")
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    r = c.post("/api/clients", json={"name": "x"}, headers=AUTH)
    assert r.status_code == 400
    assert r.json()["detail"] == "duplicate"


def test_revoke_client_calls_manager():
    mgr = _make_manager()
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    assert c.delete("/api/clients/alice", headers=AUTH).status_code == 200
    mgr.revoke_client.assert_called_once_with("alice")


def test_revoke_client_404_when_unknown():
    mgr = _make_manager()
    mgr.revoke_client.side_effect = ValueError("not found")
    app, *_ = _make_app(mgr)
    c = TestClient(app)
    assert c.delete("/api/clients/ghost", headers=AUTH).status_code == 404


def test_setup_rejects_when_already_configured():
    app, *_ = _make_app(_make_manager())
    c = TestClient(app)
    r = c.post("/api/setup", json={"endpoint": "1.2.3.4"}, headers=AUTH)
    assert r.status_code == 409


def test_setup_validates_endpoint():
    app, *_ = _make_app()
    c = TestClient(app)
    assert c.post("/api/setup", json={}, headers=AUTH).status_code == 400


def test_setup_validates_port_range():
    app, *_ = _make_app()
    c = TestClient(app)
    bad = {"endpoint": "1.2.3.4", "port": 70000}
    r = c.post("/api/setup", json=bad, headers=AUTH)
    assert r.status_code == 400


def test_setup_happy_path_invokes_callback(tmp_path):
    captured = {}

    def cb(cfg, mgr):
        captured["cfg"] = cfg
        captured["mgr"] = mgr

    app, ref, _ = _make_app(on_setup=cb)
    c = TestClient(app)

    fake_save = MagicMock()
    with (
        patch("warpsocket_server.api.default_config_dir", return_value=tmp_path),
        patch("warpsocket_server.api.default_config_path", return_value=tmp_path / "server.json"),
        patch(
            "warpsocket_server.api.generate_tls_cert",
            return_value=(tmp_path / "c.pem", tmp_path / "k.pem", "FP:FP:FP"),
        ),
        patch("warpsocket_server.api.generate_wg_keypair", return_value=("priv", "pub")),
        patch("warpsocket_server.api.shutil.which", return_value="/usr/bin/wg"),
        patch.object(ServerConfig, "save", fake_save),
    ):
        r = c.post(
            "/api/setup",
            json={
                "endpoint": "1.2.3.4",
                "port": 443,
                "wg_listen_port": 51820,
                "subnet": "10.0.0.0/24",
                "server_address": "10.0.0.1/24",
            },
            headers=AUTH,
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "fingerprint": "FP:FP:FP"}
    fake_save.assert_called_once()
    assert captured["cfg"].endpoint == "1.2.3.4"
    assert captured["mgr"] is not None


def test_detect_ip_returns_value():
    app, *_ = _make_app()

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"203.0.113.7"

    with patch("warpsocket_server.api.urllib.request.urlopen", return_value=_Resp()):
        c = TestClient(app)
        r = c.get("/api/detect-ip", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"ip": "203.0.113.7"}


def test_detect_ip_handles_error():
    app, *_ = _make_app()
    with patch("warpsocket_server.api.urllib.request.urlopen", side_effect=OSError("nope")):
        c = TestClient(app)
        r = c.get("/api/detect-ip", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ip"] is None
    assert "nope" in r.json()["error"]


def test_ws_logs_streams_lines():
    app, _, handler = _make_app()
    handler._buf.append("hello")
    c = TestClient(app)
    with c.websocket_connect(f"/api/ws/logs?token={TOKEN}") as ws:
        assert ws.receive_json() == {"line": "hello"}


def test_ws_logs_rejects_bad_token():
    app, *_ = _make_app()
    c = TestClient(app)
    with pytest.raises(Exception), c.websocket_connect("/api/ws/logs?token=nope"):
        pass


def test_static_ui_served(tmp_path):
    (tmp_path / "index.html").write_text("<html>server-ui</html>", encoding="utf-8")
    app, *_ = _make_app(ui_dir=tmp_path)
    c = TestClient(app)
    r = c.get(f"/?token={TOKEN}")
    assert r.status_code == 200
    assert "server-ui" in r.text
