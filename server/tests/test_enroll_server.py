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


def _post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
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
    # Soft-delete directly via the store rather than operations.revoke_client,
    # which would also invalidate the token itself — a different guard,
    # covered by test_a_token_cannot_be_replayed.
    from outwarp_server.client_store import ClientStore
    ServerConfig.load(config_path)  # triggers the JSON -> SQLite migration
    store = ClientStore(config_path.parent / "clients.sqlite")
    with store.transaction() as conn:
        store.soft_delete("laptop", conn=conn)

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


def test_x_forwarded_for_cannot_pick_a_rate_limit_bucket(running) -> None:
    """Every request reaches this listener through wstunnel's loopback forward,
    so the peer address is all there is to key the limiter on. A header must
    not override it: nothing in front of the listener sets a trustworthy
    X-Forwarded-For, so honouring one would let a brute-forcer rotate a fake
    origin per attempt and never trip the limit."""
    _, _, url = running

    def attempt(spoofed_ip: str) -> int:
        return _post(
            url,
            {"token": "ow_enroll_bad", "client_public_key": CLIENT_PUB},
            headers={"X-Forwarded-For": spoofed_ip},
        )[0]

    codes = [attempt(f"9.9.9.{i}") for i in range(8)]
    assert 429 in codes, f"expected a lockout despite rotating X-Forwarded-For, got {codes}"


def test_listener_binds_loopback_only_and_speaks_plain_http(tmp_path) -> None:
    """B-018: the self-signed branch used to bind 0.0.0.0 with its own TLS,
    which meant a second public port to forward. It now only ever answers on
    loopback, reached as a wstunnel TCP forward over the tunnel port; TLS is
    the transport's job."""
    config_path = tmp_path / "server_config.json"
    config = _config(tmp_path, tls_mode="self-signed")
    config.save(config_path)

    httpd = enroll_server.serve(config, config_path)
    try:
        host, port = httpd.server_address[:2]
        assert host == "127.0.0.1"
        assert port == config.enroll_port
        assert not hasattr(httpd.socket, "context"), "socket must not be TLS-wrapped"
        # A plain-HTTP POST with a garbage token is refused, not rejected at
        # the TLS layer.
        status, _ = _post(
            f"http://127.0.0.1:{port}/enroll",
            {"token": "ow_enroll_nope", "client_public_key": CLIENT_PUB},
        )
        assert status == 403
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_oversized_body_is_rejected(running) -> None:
    _, _, url = running
    status, _ = _post(url, {"token": "x" * 8192, "client_public_key": CLIENT_PUB})
    assert status == 400
