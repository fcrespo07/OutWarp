from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from outwarp_server.api import Api
from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.logs import MemoryLogHandler
from outwarp_server.server_manager import ServerState


def _make_config(clients=()):
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
        clients=list(clients),
    )


def _make_mgr(state=ServerState.STOPPED, clients=()):
    m = MagicMock()
    m.state = state
    m.config = _make_config(clients=clients)
    return m


def _make_api(manager=None):
    handler = MemoryLogHandler()
    return Api(handler, manager), handler


def test_status_when_unconfigured():
    api, _ = _make_api()
    s = api.get_status()
    assert s["status"] == "empty"
    assert s["config_present"] is False


def test_status_when_running():
    mgr = _make_mgr(state=ServerState.RUNNING)
    api, _ = _make_api(mgr)
    s = api.get_status()
    assert s["status"] == "running"
    assert s["config_present"] is True
    assert s["endpoint"] == "203.0.113.42"
    assert s["port"] == 443
    assert s["clients_count"] == 0


def test_deps_returns_shutil_which():
    api, _ = _make_api()
    with patch("outwarp_server.api.shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
        assert api.get_deps() == {"wstunnel": "/usr/bin/wstunnel", "wg": "/usr/bin/wg"}


def test_detect_public_ip_happy_path():
    api, _ = _make_api()

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"203.0.113.7"

    with patch("outwarp_server.api.urllib.request.urlopen", return_value=_Resp()):
        r = api.detect_public_ip()
    assert r == {"ip": "203.0.113.7"}


def test_detect_public_ip_error():
    api, _ = _make_api()
    with patch("outwarp_server.api.urllib.request.urlopen", side_effect=OSError("nope")):
        r = api.detect_public_ip()
    assert r["ip"] is None
    assert "nope" in r["error"]


def test_start_without_manager():
    api, _ = _make_api()
    assert api.start_service()["ok"] is False


def test_start_invokes_manager():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)
    r = api.start_service()
    assert r["ok"] is True
    mgr.start.assert_called_once()


def test_list_clients_merges_live_state():
    clients = [
        ClientEntry(name="alice", public_key="aliceKey", address="10.0.0.2/32"),
        ClientEntry(name="bob",   public_key="bobKey",   address="10.0.0.3/32"),
    ]
    mgr = _make_mgr(state=ServerState.RUNNING, clients=clients)
    api, _ = _make_api(mgr)

    fake_peer = MagicMock(
        endpoint="1.2.3.4:5", latest_handshake=10_000,
        transfer_rx=100, transfer_tx=200,
    )

    with (
        patch("outwarp_server.api.get_live_peers", return_value={"aliceKey": fake_peer}),
        patch("outwarp_server.api.time.time", return_value=10_010),
    ):
        out = api.list_clients()

    by_name = {c["name"]: c for c in out}
    assert by_name["alice"]["status"] == "online"
    assert by_name["alice"]["last_handshake_seconds_ago"] == 10
    assert by_name["alice"]["rx_bytes"] == 100
    assert by_name["bob"]["status"] == "unknown"


def test_add_client_returns_owcfg(tmp_path):
    owcfg_file = tmp_path / "alice.owcfg"
    owcfg_file.write_text('{"hi": 1}', encoding="utf-8")
    mgr = _make_mgr()
    mgr.add_client.return_value = owcfg_file

    api, _ = _make_api(mgr)
    r = api.add_client("alice")

    assert r["ok"] is True
    assert r["name"] == "alice"
    assert r["path"] == str(owcfg_file)
    assert r["owcfg"] == '{"hi": 1}'
    assert base64.b64decode(r["owcfg_base64"]) == b'{"hi": 1}'
    mgr.add_client.assert_called_once_with("alice")


def test_add_client_blank_name():
    api, _ = _make_api(_make_mgr())
    r = api.add_client("   ")
    assert r["ok"] is False
    assert "name" in r["error"].lower()


def test_add_client_handles_value_error():
    mgr = _make_mgr()
    mgr.add_client.side_effect = ValueError("dup")
    api, _ = _make_api(mgr)
    r = api.add_client("alice")
    assert r["ok"] is False
    assert r["error"] == "dup"


def test_revoke_client_happy_path():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)
    r = api.revoke_client("alice")
    assert r["ok"] is True
    mgr.revoke_client.assert_called_once_with("alice")


def test_revoke_client_not_found():
    mgr = _make_mgr()
    mgr.revoke_client.side_effect = ValueError("not found")
    api, _ = _make_api(mgr)
    r = api.revoke_client("ghost")
    assert r["ok"] is False
    assert r["error"] == "not found"


def test_run_setup_rejects_when_already_configured():
    api, _ = _make_api(_make_mgr())
    r = api.run_setup({"endpoint": "1.2.3.4"})
    assert r["ok"] is False


def test_run_setup_validates_endpoint():
    api, _ = _make_api()
    assert api.run_setup({})["ok"] is False


def test_run_setup_validates_port_range():
    api, _ = _make_api()
    assert api.run_setup({"endpoint": "1.2.3.4", "port": 70000})["ok"] is False


def test_run_setup_happy_path(tmp_path):
    api, _ = _make_api()
    captured = {}

    def cb(new_mgr):
        captured["mgr"] = new_mgr
    api._on_manager_replaced = cb

    fake_save = MagicMock()
    with (
        patch("outwarp_server.api.default_config_dir", return_value=tmp_path),
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "server.json"),
        patch("outwarp_server.api.generate_tls_cert",
              return_value=(tmp_path / "c.pem", tmp_path / "k.pem", "FP:FP:FP")),
        patch("outwarp_server.api.generate_wg_keypair", return_value=("priv", "pub")),
        patch("outwarp_server.api.shutil.which", return_value="/usr/bin/wg"),
        patch.object(ServerConfig, "save", fake_save),
    ):
        r = api.run_setup({
            "endpoint": "1.2.3.4",
            "port": 443,
            "wg_listen_port": 51820,
            "subnet": "10.0.0.0/24",
            "server_address": "10.0.0.1/24",
        })

    assert r == {"ok": True, "fingerprint": "FP:FP:FP"}
    fake_save.assert_called_once()
    assert api._manager is not None
    assert "mgr" in captured


def test_get_set_settings(tmp_path):
    with patch("outwarp_server.api.default_config_dir", return_value=tmp_path):
        api, _ = _make_api()
        r = api.set_settings({"language": "en", "advanced": True})
    assert r["settings"]["language"] == "en"
    assert (tmp_path / "gui_settings.json").exists()


def test_record_log_emits_event():
    api, _ = _make_api()
    fake_window = MagicMock()
    api._window = fake_window
    api._record_log("error", "boom")
    js = fake_window.evaluate_js.call_args.args[0]
    assert "outwarp:log" in js
    assert "boom" in js


def test_run_diagnostics_without_manager():
    api, _ = _make_api()
    r = api.run_diagnostics()
    assert r["ok"] is False
    assert "setup" in r["error"].lower()
    assert r["checks"] == []


def test_run_diagnostics_serializes_results():
    from outwarp_server.diagnostics import CheckResult, Status

    mgr = _make_mgr()
    api, _ = _make_api(mgr)

    fake_results = [
        CheckResult(name="Check OK", status=Status.PASS, detail="all good"),
        CheckResult(
            name="Check Fail",
            status=Status.FAIL,
            detail="broken",
            remediation="Run: do-the-thing",
        ),
        CheckResult(name="Check Warn", status=Status.WARN, detail="meh"),
    ]
    with patch("outwarp_server.diagnostics.run_all", return_value=fake_results):
        r = api.run_diagnostics()

    assert r["ok"] is False  # one FAIL -> ok is False
    assert r["summary"] == {"pass": 1, "warn": 1, "fail": 1, "skip": 0}
    assert r["checks"][0] == {
        "name": "Check OK", "status": "pass", "detail": "all good",
        "remediation": None, "remediation_command": None,
    }
    assert r["checks"][1]["remediation"] == "Run: do-the-thing"
    assert r["checks"][1]["status"] == "fail"
    # remediation_command defaults to None when the check didn't set it.
    assert r["checks"][1]["remediation_command"] is None
