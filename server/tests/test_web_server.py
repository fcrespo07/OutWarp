from __future__ import annotations

import http.client
import json
import ssl
import threading
import time
from unittest.mock import MagicMock

import pytest

from outwarp_server import web_server
from outwarp_server.api import Api
from outwarp_server.config import ServerConfig
from outwarp_server.crypto import generate_tls_cert
from outwarp_server.logs import MemoryLogHandler
from outwarp_server.server_manager import ServerState
from outwarp_server.web_auth import generate_and_store_token


def _make_config():
    return ServerConfig(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="secret",
        cert_path="/etc/outwarp/tls/cert.pem",
        key_path="/etc/outwarp/tls/key.pem",
        cert_fingerprint_sha256="AB" + ":AB" * 31,
        wg_private_key="priv",
        wg_public_key="pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=[],
    )


@pytest.fixture()
def panel(tmp_path):
    cert, key, _ = generate_tls_cert("localhost", tmp_path / "tls")
    token = generate_and_store_token(tmp_path)
    mgr = MagicMock()
    mgr.state = ServerState.STOPPED
    mgr.config = _make_config()
    api = Api(MemoryLogHandler(), mgr)
    httpd = web_server.serve(
        api,
        ui_dir=web_server.Path(__file__).resolve().parent.parent / "outwarp_server" / "ui",
        config_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        certfile=str(cert),
        keyfile=str(key),
    )
    yield httpd, api, token
    httpd.shutdown()


def _conn(httpd):
    port = httpd.server_address[1]
    ctx = ssl._create_unverified_context()
    return http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=5)


def _request(httpd, method, path, *, body=None, cookie=None, csrf=False):
    conn = _conn(httpd)
    headers = {"Connection": "close"}
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-OutWarp-Panel"] = "1"
    payload = json.dumps(body).encode() if body is not None else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def test_static_index_served(panel):
    httpd, _, _ = panel
    resp, data = _request(httpd, "GET", "/")
    assert resp.status == 200
    assert "text/html" in resp.getheader("Content-Type")
    assert b"<div id=\"root\">" in data
    assert resp.getheader("Content-Security-Policy") is not None


def test_static_path_traversal_blocked(panel):
    httpd, _, _ = panel
    resp, _ = _request(httpd, "GET", "/../../etc/passwd")
    assert resp.status in (403, 404)


def test_api_requires_auth(panel):
    httpd, _, _ = panel
    resp, _ = _request(httpd, "POST", "/api/get_status", body=[], csrf=True)
    assert resp.status == 401


def test_auth_bad_token_rejected(panel):
    httpd, _, _ = panel
    resp, _ = _request(httpd, "POST", "/auth", body={"token": "wrong"})
    assert resp.status == 401


def _login(httpd, token):
    resp, _ = _request(httpd, "POST", "/auth", body={"token": token})
    assert resp.status == 200
    raw = resp.getheader("Set-Cookie")
    assert raw and "HttpOnly" in raw and "Secure" in raw and "SameSite=Strict" in raw
    return raw.split(";", 1)[0]


def test_auth_then_api_call(panel):
    httpd, _, token = panel
    cookie = _login(httpd, token)
    resp, data = _request(
        httpd, "POST", "/api/get_status", body=[], cookie=cookie, csrf=True
    )
    assert resp.status == 200
    payload = json.loads(data)
    assert payload["status"] == "stopped"


def test_csrf_header_required(panel):
    httpd, _, token = panel
    cookie = _login(httpd, token)
    resp, _ = _request(
        httpd, "POST", "/api/get_status", body=[], cookie=cookie, csrf=False
    )
    assert resp.status == 403


def test_method_not_in_allowlist(panel):
    httpd, _, token = panel
    cookie = _login(httpd, token)
    resp, _ = _request(
        httpd, "POST", "/api/window_close", body=[], cookie=cookie, csrf=True
    )
    assert resp.status == 404


def test_sse_receives_event(panel):
    httpd, api, token = panel
    cookie = _login(httpd, token)
    conn = _conn(httpd)
    conn.request("GET", "/events", headers={"Cookie": cookie})
    resp = conn.getresponse()
    assert resp.status == 200
    assert "text/event-stream" in resp.getheader("Content-Type")

    # Give the SSE handler a beat to subscribe, then emit through the Api.
    time.sleep(0.2)
    api._record_log("warn", "hello over sse")

    received = {}

    def _read() -> None:
        buf = b""
        while b"hello over sse" not in buf:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
        received["buf"] = buf

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=5)
    conn.close()
    assert b"event: outwarp:log" in received.get("buf", b"")
    assert b"hello over sse" in received["buf"]
