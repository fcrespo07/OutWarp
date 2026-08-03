"""End-to-end tests for the enrolment endpoint.

These run a real listener on loopback and speak real HTTP to it: the point of
the flow is what crosses the wire, and a mocked handler would not tell us
whether a private key can leak or a token can be replayed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from outwarp_server import enroll_server, enrollment, operations
from outwarp_server.config import ClientEntry, ServerConfig

# A syntactically valid WireGuard public key (32 base64 bytes).
CLIENT_PUB = "hV+FLtHOe6X8HQPULlV/uPJyMfWkoNTPBz9jXqbYb2s="
OTHER_PUB = "TGlnaHRob3VzZUtleUZvclRlc3RpbmcxMjM0NTY3OD0="


def _config(tmp_path: Path, **overrides) -> ServerConfig:
    base = ServerConfig(
        schema_version=1,
        endpoint="127.0.0.1",
        port=443,
        http_upgrade_path_prefix="s3cr3t",
        cert_path=str(tmp_path / "cert.pem"),
        key_path=str(tmp_path / "key.pem"),
        cert_fingerprint_sha256="AB:" * 31 + "AB",
        wg_private_key="srv_priv",
        wg_public_key="srv_pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        # Loopback + no TLS wrapping keeps the test about the protocol; the TLS
        # branch is exercised by test_web_server, which shares the same wrapper.
        tls_mode="acme",
        enroll_port=_free_port(),
        clients=[],
    )
    return replace(base, **overrides)


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running(tmp_path, monkeypatch):
    """A live listener plus a server config holding one reserved slot."""
    monkeypatch.setattr(
        operations, "_persist_wg_config", lambda _cfg: None
    )
    monkeypatch.setattr(operations, "add_peer_live", lambda *a, **k: None)

    config_path = tmp_path / "server_config.json"
    config = _config(
        tmp_path,
        clients=[ClientEntry(name="laptop", public_key="", address="10.0.0.2/32", psk="")],
    )
    config.save(config_path)

    httpd = enroll_server.serve(config, config_path)
    port = httpd.server_address[1]
    try:
        yield tmp_path, config_path, f"http://127.0.0.1:{port}/enroll"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {}


def test_redeeming_registers_the_public_key(running) -> None:
    config_dir, config_path, url = running
    token = enrollment.issue(config_dir, "laptop")

    status, body = _post(url, {"token": token, "client_public_key": CLIENT_PUB})

    assert status == 200
    assert body["ok"] is True
    assert body["client_address"] == "10.0.0.2/32"

    saved = ServerConfig.load(config_path)
    assert saved.clients[0].public_key == CLIENT_PUB


def test_a_token_cannot_be_replayed(running) -> None:
    """Interception is only detectable if the second redemption fails loudly."""
    config_dir, config_path, url = running
    token = enrollment.issue(config_dir, "laptop")

    assert _post(url, {"token": token, "client_public_key": CLIENT_PUB})[0] == 200
    status, body = _post(url, {"token": token, "client_public_key": OTHER_PUB})

    assert status == 403
    assert "already redeemed" in body["error"]
    # The first client keeps the slot; the replay changed nothing.
    assert ServerConfig.load(config_path).clients[0].public_key == CLIENT_PUB


def test_unknown_token_is_refused(running) -> None:
    _, config_path, url = running
    status, _ = _post(url, {"token": "ow_enroll_nope", "client_public_key": CLIENT_PUB})
    assert status == 403
    assert ServerConfig.load(config_path).clients[0].public_key == ""


def test_a_malformed_public_key_is_rejected_before_the_token_is_spent(running) -> None:
    config_dir, _, url = running
    token = enrollment.issue(config_dir, "laptop")

    status, body = _post(url, {"token": token, "client_public_key": "not-a-key"})

    assert status == 400
    assert "public key" in body["error"]
    # Still redeemable — a typo must not burn the client's one chance.
    assert enrollment.redeem(config_dir, token).client_name == "laptop"


def test_revoked_reservation_cannot_be_claimed(running) -> None:
    config_dir, config_path, url = running
    token = enrollment.issue(config_dir, "laptop")
    # Admin removed the client after issuing but before the client redeemed.
    config = replace(ServerConfig.load(config_path), clients=[])
    config.save(config_path)

    status, body = _post(url, {"token": token, "client_public_key": CLIENT_PUB})

    assert status == 409
    assert "no longer registered" in body["error"]


def test_a_slot_that_already_enrolled_is_not_overwritten(running) -> None:
    config_dir, config_path, url = running
    first = enrollment.issue(config_dir, "laptop")
    _post(url, {"token": first, "client_public_key": CLIENT_PUB})

    second = enrollment.issue(config_dir, "laptop")
    status, _ = _post(url, {"token": second, "client_public_key": OTHER_PUB})

    assert status == 409
    assert ServerConfig.load(config_path).clients[0].public_key == CLIENT_PUB


def test_get_is_not_a_route(running) -> None:
    _, _, url = running
    try:
        with urllib.request.urlopen(url, timeout=10):
            pytest.fail("GET should not be served")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_wrong_path_is_not_a_route(running) -> None:
    _, _, url = running
    status, _ = _post(url.replace("/enroll", "/admin"), {"token": "x"})
    assert status == 404


def test_repeated_failures_are_rate_limited(running) -> None:
    _, _, url = running
    codes = [
        _post(url, {"token": f"ow_enroll_bad{i}", "client_public_key": CLIENT_PUB})[0]
        for i in range(8)
    ]
    assert 429 in codes, f"expected a lockout after repeated bad tokens, got {codes}"


def test_oversized_body_is_rejected(running) -> None:
    _, _, url = running
    status, _ = _post(url, {"token": "x" * 8192, "client_public_key": CLIENT_PUB})
    assert status == 400
