"""Enrolment over the transport, against the real wstunnel binary.

The unit tests pin the argv on both sides; this is the one place that proves
wstunnel 10.x actually honours it: a `-L tcp://` client forward reaches the
loopback listener through the restricted server, and a forward to any other
destination is refused. Skipped where wstunnel is not installed (CI).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from outwarp_server import crypto, enroll_server, enrollment, operations
from outwarp_server.binaries import find_wstunnel
from outwarp_server.client_store import ClientStore
from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.server_manager import build_wstunnel_command

WSTUNNEL = find_wstunnel()
pytestmark = pytest.mark.skipif(WSTUNNEL is None, reason="wstunnel binary not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wg_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _wait_port(port: int, proc: subprocess.Popen, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert proc.poll() is None, "wstunnel exited early"
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"port {port} never opened")


@pytest.fixture
def transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real wstunnel server (restricted like production) + real listener."""
    cert, key, fp, spki = crypto.generate_tls_cert("127.0.0.1", tmp_path / "tls")
    config = ServerConfig(
        schema_version=1, endpoint="127.0.0.1", port=_free_port(),
        http_upgrade_path_prefix="s3cr3t", cert_path=str(cert), key_path=str(key),
        cert_fingerprint_sha256=fp, spki_sha256=spki,
        wg_private_key=_wg_key(), wg_public_key=_wg_key(),
        subnet="10.0.0.0/24", server_address="10.0.0.1/24",
        wg_listen_port=_free_port(), enroll_port=_free_port(), clients=[],
    )
    config_path = tmp_path / "server_config.json"
    monkeypatch.setattr(operations, "_persist_wg_config", lambda _c: None)
    monkeypatch.setattr(operations, "add_peer_live", lambda *a, **k: None)
    store = ClientStore(tmp_path / "clients.sqlite")
    with store.transaction() as conn:
        store.insert(
            ClientEntry(name="laptop", public_key="", address="10.0.0.2/32", psk=""),
            conn=conn, created_at="2026-01-01",
        )
    config = replace(config, clients=store.list_active())
    config.save(config_path)

    httpd = enroll_server.serve(config, config_path)
    server = subprocess.Popen(
        build_wstunnel_command(config, WSTUNNEL),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port(config.port, server)
        yield config, config_path, store
    finally:
        server.terminate()
        server.wait(timeout=5)
        httpd.shutdown()
        httpd.server_close()


def _forward(config: ServerConfig, remote_port: int) -> tuple[subprocess.Popen, int]:
    """What the client's outwarp.enroll._forward_command renders, without
    importing the client package into the server's test environment."""
    local = _free_port()
    proc = subprocess.Popen(
        [
            str(WSTUNNEL), "client",
            "-L", f"tcp://127.0.0.1:{local}:127.0.0.1:{remote_port}",
            "--http-upgrade-path-prefix", config.http_upgrade_path_prefix,
            f"wss://127.0.0.1:{config.port}",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _wait_port(local, proc)
    return proc, local


def _post(local_port: int, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{local_port}/enroll",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_token_is_redeemed_through_the_tunnel_port(transport) -> None:
    config, config_path, store = transport
    token = enrollment.issue(config_path.parent, "laptop", ttl_seconds=60)
    public_key = _wg_key()

    proc, local = _forward(config, config.enroll_port)
    try:
        status, payload = _post(local, {"token": token, "client_public_key": public_key})
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert status == 200, payload
    assert payload["name"] == "laptop"
    assert payload["client_address"] == "10.0.0.2/32"
    assert next(c for c in store.list_active() if c.name == "laptop").public_key == public_key


def test_forwards_outside_the_restriction_are_refused(transport) -> None:
    """`--restrict-to` is what stops the secret path from becoming a generic
    TCP proxy into the server: only WireGuard and the listener are reachable."""
    config, _config_path, _store = transport
    proc, local = _forward(config, config.enroll_port + 1)
    try:
        with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
            urllib.request.urlopen(f"http://127.0.0.1:{local}/enroll", data=b"{}", timeout=5)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
