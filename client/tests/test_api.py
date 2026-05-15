from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from outwarp.api import Api
from outwarp.logs import MemoryLogHandler
from outwarp.tunnel import TunnelState

_VALID_OWCFG = {
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
        "tunnel_name": "OutWarp",
        "client_address": "10.0.0.42/32",
        "client_private_key": "dGVzdGtleQ==",
        "server_public_key": "c2VydmVya2V5",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
}


def _make_api(manager=None):
    handler = MemoryLogHandler()
    return Api(handler, manager), handler


def test_get_status_without_manager():
    api, _ = _make_api()
    s = api.get_status()
    assert s["status"] == "empty"
    assert s["active_profile_id"] is None
    assert s["stats"]["tx_total"] == 0


def test_get_status_with_manager_reflects_tunnel_state():
    mgr = MagicMock()
    mgr.state = TunnelState.CONNECTED
    mgr.config.server.endpoint = "1.2.3.4"
    mgr.config.server.port = 443
    mgr.config.wireguard.tunnel_name = "WG"
    api, _ = _make_api(mgr)
    s = api.get_status()
    assert s["status"] == "connected"
    assert s["active_profile_id"] == "WG"


def test_connect_without_manager_returns_error():
    api, _ = _make_api()
    r = api.connect()
    assert r == {"ok": False, "error": "no profile imported"}


def test_connect_starts_manager():
    mgr = MagicMock()
    api, _ = _make_api(mgr)
    r = api.connect()
    assert r["ok"] is True
    mgr.start.assert_called_once()


def test_disconnect_runs_stop_in_thread():
    mgr = MagicMock()
    api, _ = _make_api(mgr)
    r = api.disconnect()
    assert r["ok"] is True
    # The endpoint dispatches stop() to a daemon thread; wait briefly.
    import time
    for _ in range(50):
        if mgr.stop.called:
            break
        time.sleep(0.01)
    mgr.stop.assert_called_once()


def test_list_profiles_empty_when_no_manager():
    api, _ = _make_api()
    assert api.list_profiles() == []


def test_list_profiles_returns_active_only():
    mgr = MagicMock()
    mgr.config.name = ""  # falls back to tunnel_name as the display name
    mgr.config.server.endpoint = "1.2.3.4"
    mgr.config.server.port = 443
    mgr.config.tls.cert_fingerprint_sha256 = "AB:CD"
    mgr.config.wireguard.tunnel_name = "WG"
    mgr.config.wireguard.client_address = "10.0.0.2/32"
    mgr.config.wireguard.dns = ["1.1.1.1"]
    api, _ = _make_api(mgr)
    profiles = api.list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "WG"
    assert profiles[0]["endpoint"] == "1.2.3.4:443"
    assert profiles[0]["fingerprint"] == "AB:CD"


def test_import_profile_invalid_returns_error():
    api, _ = _make_api()
    r = api.import_profile("not a json")
    assert r["ok"] is False
    assert "error" in r


def test_import_profile_replaces_manager(tmp_path):
    api, _ = _make_api()
    captured = {}

    def on_replace(new_mgr):
        captured["mgr"] = new_mgr

    api._on_manager_replaced = on_replace

    fake_tm = MagicMock()
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.TunnelManager", return_value=fake_tm),
    ):
        r = api.import_profile(json.dumps(_VALID_OWCFG))

    assert r["ok"] is True
    assert r["profile"]["endpoint"] == "203.0.113.42:443"
    assert captured["mgr"] is fake_tm
    assert api._manager is fake_tm
    fake_tm.add_listener.assert_called_once()


def test_get_set_settings_round_trip(tmp_path):
    with patch(
        "outwarp.api.default_config_path",
        return_value=tmp_path / "config.json",
    ):
        api, _ = _make_api()
        r = api.set_settings({"language": "en", "advanced": True})
    assert r["settings"]["language"] == "en"
    assert r["settings"]["advanced"] is True
    # settings.json was written next to config.json
    settings_path = tmp_path / "settings.json"
    assert settings_path.exists()
    saved = json.loads(settings_path.read_text())
    assert saved["language"] == "en"


def test_set_settings_ignores_unknown_keys(tmp_path):
    with patch(
        "outwarp.api.default_config_path",
        return_value=tmp_path / "config.json",
    ):
        api, _ = _make_api()
        r = api.set_settings({"language": "en", "unknown_key": "x"})
    assert "unknown_key" not in r["settings"]


def test_default_settings_include_auto_reconnect(tmp_path):
    with patch(
        "outwarp.api.default_config_path",
        return_value=tmp_path / "config.json",
    ):
        api, _ = _make_api()
        s = api.get_settings()
    assert s["auto_reconnect"] is True


def test_set_settings_propagates_auto_reconnect_to_manager(tmp_path):
    mgr = MagicMock()
    mgr.state = TunnelState.DISCONNECTED
    mgr.auto_reconnect = True
    with patch(
        "outwarp.api.default_config_path",
        return_value=tmp_path / "config.json",
    ):
        api, _ = _make_api(mgr)
        api.set_settings({"auto_reconnect": False})
    # The setter on the manager is what gets called; MagicMock records the
    # assignment, so verify by reading back.
    assert mgr.auto_reconnect is False


def test_settings_propagated_to_manager_on_construction(tmp_path):
    """When Api is built with a manager, the persisted settings are pushed
    onto it so existing tunnels honour the latest user prefs."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"auto_reconnect": False}))
    mgr = MagicMock()
    mgr.state = TunnelState.DISCONNECTED
    with patch(
        "outwarp.api.default_config_path",
        return_value=tmp_path / "config.json",
    ):
        Api(MemoryLogHandler(), mgr)
    assert mgr.auto_reconnect is False


def test_state_change_emits_status_event():
    mgr = MagicMock()
    mgr.state = TunnelState.DISCONNECTED
    mgr.config.server.endpoint = "x"
    mgr.config.server.port = 1
    mgr.config.wireguard.tunnel_name = "t"
    api, _ = _make_api(mgr)
    fake_window = MagicMock()
    api._window = fake_window

    api._on_state_change(TunnelState.CONNECTED)
    # The first event emitted is outwarp:status; CONNECTED also kicks off the
    # stats heartbeat thread which can emit additional outwarp:stats events.
    status_calls = [
        c.args[0] for c in fake_window.evaluate_js.call_args_list
        if "outwarp:status" in c.args[0]
    ]
    assert status_calls, "no outwarp:status event was emitted"
    assert '"status": "connected"' in status_calls[0]
    api._stop_stats_loop()


def test_get_logs_returns_buffer():
    api, _ = _make_api()
    api._record_log("info", "first")
    api._record_log("error", "second")
    all_logs = api.get_logs(0)
    assert len(all_logs) == 2
    assert all_logs[0]["msg"] == "first"
    assert all_logs[1]["level"] == "error"

    after_first = api.get_logs(1)
    assert len(after_first) == 1
    assert after_first[0]["msg"] == "second"


# ── profile editing ───────────────────────────────────────────────────────

def _real_config(tmp_path, **overrides):
    from outwarp.config import ClientConfig
    data = json.loads(json.dumps(_VALID_OWCFG))
    data.update(overrides)
    src = tmp_path / "src.owcfg"
    src.write_text(json.dumps(data), encoding="utf-8")
    return ClientConfig.load(src)


def _mgr_with_config(cfg, state=TunnelState.DISCONNECTED):
    mgr = MagicMock()
    mgr.config = cfg
    mgr.state = state
    return mgr


def test_update_profile_without_manager_errors():
    api, _ = _make_api()
    r = api.update_profile("x", {"mtu": 1400})
    assert r["ok"] is False


def test_update_profile_applies_and_persists(tmp_path):
    cfg = _real_config(tmp_path)
    api, _ = _make_api(_mgr_with_config(cfg))
    with (
        patch("outwarp.api.default_config_path", return_value=tmp_path / "config.json"),
        patch("outwarp.api.TunnelManager", return_value=MagicMock()),
    ):
        r = api.update_profile("OutWarp", {"name": "Trabajo", "mtu": 1400, "dns": "9.9.9.9, 1.1.1.1"})
    assert r["ok"] is True
    assert r["profile"]["name"] == "Trabajo"
    assert r["profile"]["mtu"] == 1400
    assert r["profile"]["dns"] == ["9.9.9.9", "1.1.1.1"]
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["wireguard"]["mtu"] == 1400
    assert saved["name"] == "Trabajo"
    # pre-edit state was snapshotted so reset has a baseline
    assert (tmp_path / "config.original.json").exists()


def test_update_profile_rejects_invalid_value(tmp_path):
    cfg = _real_config(tmp_path)
    api, _ = _make_api(_mgr_with_config(cfg))
    with patch("outwarp.api.default_config_path", return_value=tmp_path / "config.json"):
        r = api.update_profile("OutWarp", {"mtu": 99999})
    assert r["ok"] is False
    assert "MTU" in r["error"]


def test_reset_profile_restores_original(tmp_path):
    original = _real_config(tmp_path)
    original.save(tmp_path / "config.original.json")
    edited = _real_config(tmp_path, name="Editado")
    api, _ = _make_api(_mgr_with_config(edited))
    with (
        patch("outwarp.api.default_config_path", return_value=tmp_path / "config.json"),
        patch("outwarp.api.TunnelManager", return_value=MagicMock()),
    ):
        r = api.reset_profile("OutWarp")
    assert r["ok"] is True
    # _VALID_OWCFG carries no name field, so the display name falls back to the
    # interface name — the point is that the "Editado" edit was discarded.
    assert r["profile"]["name"] == "OutWarp"
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["wireguard"]["mtu"] == 1380
    assert saved["name"] == ""


def test_reset_profile_without_baseline_errors(tmp_path):
    cfg = _real_config(tmp_path)
    api, _ = _make_api(_mgr_with_config(cfg))
    with patch("outwarp.api.default_config_path", return_value=tmp_path / "config.json"):
        r = api.reset_profile("OutWarp")
    assert r["ok"] is False
