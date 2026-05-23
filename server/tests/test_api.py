from __future__ import annotations

import base64
from pathlib import Path
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


def test_deps_returns_resolved_paths():
    api, _ = _make_api()
    with patch("outwarp_server.api.find_wstunnel", return_value=Path("/usr/bin/wstunnel")), \
         patch("outwarp_server.api.find_wg", return_value=Path("/usr/bin/wg")):
        assert api.get_deps() == {
            "wstunnel": str(Path("/usr/bin/wstunnel")),
            "wg": str(Path("/usr/bin/wg")),
        }


def test_deps_returns_none_when_missing():
    api, _ = _make_api()
    with patch("outwarp_server.api.find_wstunnel", return_value=None), \
         patch("outwarp_server.api.find_wg", return_value=None):
        assert api.get_deps() == {"wstunnel": None, "wg": None}


def test_cli_status_unsupported_off_windows():
    api, _ = _make_api()
    with patch("outwarp_server.api.sys.platform", "linux"):
        assert api.get_cli_status() == {
            "supported": False, "available": False, "enabled": False, "cli_dir": None,
        }
    with patch("outwarp_server.api.sys.platform", "linux"):
        assert api.set_cli_enabled(True)["ok"] is False


def test_cli_enable_disable_edits_user_path(tmp_path):
    api, _ = _make_api()
    (tmp_path / "outwarp-server.exe").write_text("x")
    store = {"entries": [r"C:\Windows\System32"], "type": 2}

    def _read():
        return list(store["entries"]), store["type"]

    def _write(entries, vtype):
        store["entries"] = list(entries)
        store["type"] = vtype

    with patch("outwarp_server.api.sys.platform", "win32"), \
         patch("outwarp_server.api._cli_dir", return_value=tmp_path), \
         patch("outwarp_server.api._read_user_path", side_effect=_read), \
         patch("outwarp_server.api._write_user_path", side_effect=_write), \
         patch("outwarp_server.api._save_settings"):
        st0 = api.get_cli_status()
        assert st0["supported"] and st0["available"] and not st0["enabled"]

        assert api.set_cli_enabled(True)["ok"] is True
        assert str(tmp_path) in store["entries"]
        assert api.get_cli_status()["enabled"] is True

        assert api.set_cli_enabled(False)["ok"] is True
        assert str(tmp_path) not in store["entries"]


def test_cli_enable_fails_without_exe(tmp_path):
    api, _ = _make_api()
    with patch("outwarp_server.api.sys.platform", "win32"), \
         patch("outwarp_server.api._cli_dir", return_value=tmp_path):
        # no outwarp-server.exe present in tmp_path
        r = api.set_cli_enabled(True)
    assert r["ok"] is False


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
    mgr.add_client.assert_called_once_with("alice", expires_at="")


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
        patch("outwarp_server.api.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
        patch("outwarp_server.api.find_wg", return_value=Path("/usr/bin/wg")),
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


# ── B.3 client detail / rotate ─────────────────────────────────────────────

def test_get_app_info_returns_versioned_payload():
    api, _ = _make_api()
    info = api.get_app_info()
    assert "version" in info and info["version"]
    assert info["license"] == "MIT"
    assert info["repo_url"].startswith("https://github.com/")
    assert any(t["name"] == "wstunnel" for t in info["third_party"])


def test_open_url_invokes_webbrowser():
    api, _ = _make_api()
    with patch("webbrowser.open") as mock_open:
        r = api.open_url("https://example.com")
    assert r["ok"] is True
    mock_open.assert_called_once_with("https://example.com", new=2)


def test_get_client_not_found():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        r = api.get_client("ghost")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_get_client_happy_path():
    client = ClientEntry(name="alice", public_key="PK", address="10.0.0.5/32")
    mgr = _make_mgr(clients=[client])
    api, _ = _make_api(mgr)
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        r = api.get_client("alice")
    assert r["ok"] is True
    assert r["name"] == "alice"
    assert r["address"] == "10.0.0.5/32"
    assert r["public_key"] == "PK"
    assert r["allowed_ips"] == ["10.0.0.5/32"]


def test_rotate_client_keys_happy_path(tmp_path):
    mgr = _make_mgr()
    written = tmp_path / "alice.owcfg"
    written.write_bytes(b"new-owcfg")
    mgr.rotate_client_keys.return_value = (written, "NEW_PUB")

    api, _ = _make_api(mgr)
    fake_window = MagicMock()
    api.bind_window(fake_window)
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        r = api.rotate_client_keys("alice")
    assert r["ok"] is True
    assert r["name"] == "alice"
    assert r["public_key"] == "NEW_PUB"
    assert base64.b64decode(r["owcfg_base64"]) == b"new-owcfg"


def test_rotate_client_keys_unknown_name():
    mgr = _make_mgr()
    mgr.rotate_client_keys.side_effect = ValueError("not found")
    api, _ = _make_api(mgr)
    r = api.rotate_client_keys("ghost")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_regenerate_owcfg_delegates_to_rotate(tmp_path):
    mgr = _make_mgr()
    written = tmp_path / "alice.owcfg"
    written.write_bytes(b"regen")
    mgr.rotate_client_keys.return_value = (written, "PUB2")
    api, _ = _make_api(mgr)
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        r = api.regenerate_owcfg("alice")
    assert r["ok"] is True
    mgr.rotate_client_keys.assert_called_once_with("alice")


# ── B.4 logs ───────────────────────────────────────────────────────────────

def test_clear_logs_empties_buffer():
    api, _ = _make_api()
    api._record_log("info", "hello")
    api._record_log("info", "world")
    assert len(api._logs) == 2
    r = api.clear_logs()
    assert r["ok"] is True
    assert len(api._logs) == 0


def test_export_logs_writes_file(tmp_path):
    import sys
    api, _ = _make_api()
    api._record_log("info", "line one")
    api._record_log("error", "line two")
    out = tmp_path / "out.txt"
    fake_window = MagicMock()
    fake_window.create_file_dialog.return_value = str(out)
    api._window = fake_window
    with patch.dict(sys.modules, {"webview": MagicMock(SAVE_DIALOG=2)}):
        r = api.export_logs()
    assert r["ok"] is True
    text = out.read_text(encoding="utf-8")
    assert "line one" in text
    assert "[ERROR] line two" in text


def test_export_logs_cancelled():
    import sys
    api, _ = _make_api()
    fake_window = MagicMock()
    fake_window.create_file_dialog.return_value = None
    api._window = fake_window
    with patch.dict(sys.modules, {"webview": MagicMock(SAVE_DIALOG=2)}):
        r = api.export_logs()
    assert r["ok"] is False
    assert r["error"] == "cancelled"


# ── B.5 server config updates / cert rotation ─────────────────────────────

def test_update_server_config_no_manager():
    api, _ = _make_api()
    assert api.update_server_config({"port": 8443})["ok"] is False


def test_update_server_config_validates_port():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)
    r = api.update_server_config({"port": 70000})
    assert r["ok"] is False
    assert "range" in r["error"]


def test_update_server_config_happy_path(tmp_path):
    mgr = _make_mgr()
    # Real manager would mutate ._config; mock just accepts the assignment.
    mgr._config = mgr.config
    api, _ = _make_api(mgr)
    fake_save = MagicMock()
    with (
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save", fake_save),
    ):
        r = api.update_server_config({"port": 8443, "endpoint": "1.2.3.4"})
    assert r["ok"] is True
    fake_save.assert_called_once()


def test_rotate_tls_cert_happy_path(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    api, _ = _make_api(mgr)
    fake_save = MagicMock()
    with (
        patch("outwarp_server.api.generate_tls_cert",
              return_value=(tmp_path / "c.pem", tmp_path / "k.pem", "NEW:FP:FP")),
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save", fake_save),
    ):
        r = api.rotate_tls_cert()
    assert r["ok"] is True
    assert r["fingerprint"] == "NEW:FP:FP"


# ── Bug-1/Bug-2 fix: platform-aware bouncing ───────────────────────────────
# The bounce runs in a background thread; these tests patch threading.Thread
# to fire the target synchronously so we can assert about what got called.


def _sync_thread():
    """Replacement for threading.Thread that runs target synchronously on .start()."""
    class _T:
        def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)
    return _T


def test_update_server_config_restarts_systemd_when_running(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    mgr._wstunnel = None  # subprocess path inactive
    api, _ = _make_api(mgr)

    fake_platform = MagicMock()
    fake_platform.is_wstunnel_running.return_value = True
    fake_platform.is_wg_active.return_value = True

    with (
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save"),
        patch("outwarp_server.api.get_server_platform", return_value=fake_platform),
        patch("outwarp_server.api.threading.Thread", _sync_thread()),
        patch("outwarp_server.api.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
    ):
        r = api.update_server_config({"port": 8443})

    assert r["ok"] is True
    # Port changed → install_wstunnel_service rewrites the unit AND restart fires.
    fake_platform.install_wstunnel_service.assert_called_once()
    fake_platform.restart_wstunnel_service.assert_called_once()
    # Subprocess path is inactive — manager.restart() must NOT be called.
    mgr.restart.assert_not_called()


def test_update_server_config_bounces_subprocess_when_no_systemd(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    # Pretend the subprocess flow is active (GUI dev mode).
    mgr._wstunnel = MagicMock()
    api, _ = _make_api(mgr)

    fake_platform = MagicMock()
    fake_platform.is_wstunnel_running.return_value = False
    fake_platform.is_wg_active.return_value = False

    with (
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save"),
        patch("outwarp_server.api.get_server_platform", return_value=fake_platform),
        patch("outwarp_server.api.threading.Thread", _sync_thread()),
    ):
        r = api.update_server_config({"endpoint": "9.9.9.9"})

    assert r["ok"] is True
    # No systemd-managed service → don't touch it.
    fake_platform.install_wstunnel_service.assert_not_called()
    fake_platform.restart_wstunnel_service.assert_not_called()
    # Subprocess present → bounce it.
    mgr.restart.assert_called_once()


def test_update_server_config_restarts_wg_on_port_change(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    mgr._wstunnel = None
    api, _ = _make_api(mgr)

    fake_platform = MagicMock()
    fake_platform.is_wstunnel_running.return_value = False
    fake_platform.is_wg_active.return_value = True

    with (
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save"),
        patch("outwarp_server.api.get_server_platform", return_value=fake_platform),
        patch("outwarp_server.api.threading.Thread", _sync_thread()),
    ):
        r = api.update_server_config({"wg_listen_port": 51999})

    assert r["ok"] is True
    # wg_listen_port changed → must do a full restart_wg, not just install_wg_config
    # (syncconf cannot change ListenPort on a live interface).
    fake_platform.restart_wg.assert_called_once()
    fake_platform.install_wg_config.assert_not_called()


def test_update_server_config_only_syncconf_when_wg_port_unchanged(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    mgr._wstunnel = None
    api, _ = _make_api(mgr)

    fake_platform = MagicMock()
    fake_platform.is_wstunnel_running.return_value = False
    fake_platform.is_wg_active.return_value = True

    with (
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save"),
        patch("outwarp_server.api.get_server_platform", return_value=fake_platform),
        patch("outwarp_server.api.threading.Thread", _sync_thread()),
    ):
        r = api.update_server_config({"endpoint": "5.5.5.5"})

    assert r["ok"] is True
    # WG port unchanged → install_wg_config (which does syncconf), no full restart.
    fake_platform.restart_wg.assert_not_called()
    fake_platform.install_wg_config.assert_called_once()


def test_rotate_tls_cert_restarts_systemd_when_running(tmp_path):
    mgr = _make_mgr()
    mgr._config = mgr.config
    mgr._wstunnel = None
    api, _ = _make_api(mgr)

    fake_platform = MagicMock()
    fake_platform.is_wstunnel_running.return_value = True

    with (
        patch("outwarp_server.api.generate_tls_cert",
              return_value=(tmp_path / "c.pem", tmp_path / "k.pem", "ROTATED:FP")),
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch.object(ServerConfig, "save"),
        patch("outwarp_server.api.get_server_platform", return_value=fake_platform),
        patch("outwarp_server.api.threading.Thread", _sync_thread()),
    ):
        r = api.rotate_tls_cert()

    assert r["ok"] is True
    assert r["fingerprint"] == "ROTATED:FP"
    # Cert files overwritten in place; no need to rewrite the systemd unit,
    # but the running service MUST be restarted to re-read the cert.
    fake_platform.install_wstunnel_service.assert_not_called()
    fake_platform.restart_wstunnel_service.assert_called_once()


# ── B.6 setup wizard + external port probe ────────────────────────────────

def test_run_setup_emits_progress_and_done_events(tmp_path):
    api, _ = _make_api()
    fake_window = MagicMock()
    api._window = fake_window
    fake_save = MagicMock()
    with (
        patch("outwarp_server.api.default_config_dir", return_value=tmp_path),
        patch("outwarp_server.api.default_config_path", return_value=tmp_path / "srv.json"),
        patch("outwarp_server.api.generate_tls_cert",
              return_value=(tmp_path / "c.pem", tmp_path / "k.pem", "FP:FP")),
        patch("outwarp_server.api.generate_wg_keypair", return_value=("priv", "pub")),
        patch("outwarp_server.api.find_wstunnel", return_value=Path("/usr/bin/wstunnel")),
        patch("outwarp_server.api.find_wg", return_value=Path("/usr/bin/wg")),
        patch.object(ServerConfig, "save", fake_save),
        patch.object(Api, "_run_setup_probe"),  # don't hit network in tests
    ):
        r = api.run_setup({
            "endpoint": "1.2.3.4", "port": 443, "wg_listen_port": 51820,
            "subnet": "10.0.0.0/24", "server_address": "10.0.0.1/24",
        })
    assert r["ok"] is True
    # Emitted events landed as evaluate_js calls; check phase markers fired.
    js_calls = [c.args[0] for c in fake_window.evaluate_js.call_args_list]
    blob = "\n".join(js_calls)
    for phase in ("deps", "cert", "systemd", "probe", "done"):
        assert f"'phase': '{phase}'" in blob or f'"phase": "{phase}"' in blob
    assert "setup_done" in blob


def test_run_setup_fails_when_deps_missing(tmp_path):
    api, _ = _make_api()
    fake_window = MagicMock()
    api._window = fake_window
    with patch("outwarp_server.api.find_wstunnel", return_value=None), \
         patch("outwarp_server.api.find_wg", return_value=None):
        r = api.run_setup({"endpoint": "1.2.3.4"})
    assert r["ok"] is False
    assert "missing dependencies" in r["error"]


def test_probe_external_port_no_manager():
    api, _ = _make_api()
    r = api.probe_external_port()
    assert r["reachable"] is False


def test_probe_external_port_returns_reachable_true():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ip":"1.2.3.4","port":443,"reachable":true}'

    with patch("outwarp_server.api.urllib.request.urlopen", return_value=_Resp()):
        r = api.probe_external_port()
    assert r["reachable"] is True


def test_probe_external_port_returns_reachable_false_on_error():
    mgr = _make_mgr()
    api, _ = _make_api(mgr)
    with patch("outwarp_server.api.urllib.request.urlopen", side_effect=OSError("blocked")):
        r = api.probe_external_port()
    assert r["reachable"] is False
    assert "blocked" in r["detail"]
