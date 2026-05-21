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


# --- start_at_boot ---

def test_default_settings_include_start_at_boot_off(tmp_path):
    with patch("outwarp.api.default_config_path",
               return_value=tmp_path / "config.json"):
        api, _ = _make_api()
    assert api.get_settings()["start_at_boot"] is False


def test_set_start_at_boot_true_calls_install_autostart(tmp_path):
    fake_plat = MagicMock()
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api()
        r = api.set_settings({"start_at_boot": True})
    assert r["ok"] is True
    fake_plat.install_autostart.assert_called_once()
    fake_plat.uninstall_autostart.assert_not_called()
    # The argv passed should be a non-empty list (sys.executable + maybe -m).
    cmd = fake_plat.install_autostart.call_args[0][0]
    assert isinstance(cmd, list) and len(cmd) >= 1


def test_set_start_at_boot_false_calls_uninstall_autostart(tmp_path):
    fake_plat = MagicMock()
    # Pre-seed settings.json with start_at_boot=True so the False patch is
    # an actual transition (the side effect only fires on a change).
    (tmp_path / "settings.json").write_text(json.dumps({"start_at_boot": True}))
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api()
        r = api.set_settings({"start_at_boot": False})
    assert r["ok"] is True
    fake_plat.uninstall_autostart.assert_called_once()
    fake_plat.install_autostart.assert_not_called()


def test_set_start_at_boot_no_op_when_value_unchanged(tmp_path):
    """Toggling to the same value shouldn't touch the registry / desktop file
    — that would be wasted I/O and could prompt UAC in scary edge cases."""
    fake_plat = MagicMock()
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api()
        # Default is False; setting to False again is a no-op.
        api.set_settings({"start_at_boot": False})
    fake_plat.install_autostart.assert_not_called()
    fake_plat.uninstall_autostart.assert_not_called()


def test_set_start_at_boot_rolls_back_on_platform_error(tmp_path):
    """If install_autostart raises, the persisted setting is reverted so the
    UI doesn't show 'on' when no registration actually exists."""
    from outwarp.platforms import PlatformError

    fake_plat = MagicMock()
    fake_plat.install_autostart.side_effect = PlatformError("registry locked")
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api()
        r = api.set_settings({"start_at_boot": True})
    assert r["ok"] is False
    assert "registry locked" in r["error"]
    assert r["settings"]["start_at_boot"] is False
    # Persisted value reverted too — not just the in-memory snapshot.
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["start_at_boot"] is False


# --- kill_switch ---

def _mgr_with_bypass(state, bypass_ips):
    mgr = MagicMock()
    mgr.state = state
    mgr.config.routing.bypass_ips = bypass_ips
    mgr.config.server.endpoint = "1.2.3.4"
    mgr.config.server.port = 443
    mgr.config.wireguard.tunnel_name = "WG"
    return mgr


def test_default_settings_include_kill_switch_off(tmp_path):
    with patch("outwarp.api.default_config_path",
               return_value=tmp_path / "config.json"):
        api, _ = _make_api()
    assert api.get_settings()["kill_switch"] is False


def test_kill_switch_engages_on_failed_when_enabled(tmp_path):
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.FAILED)
    fake_plat.engage_kill_switch.assert_called_once_with(["203.0.113.42"])
    fake_plat.release_kill_switch.assert_not_called()


def test_kill_switch_engages_on_reconnecting_too(tmp_path):
    """RECONNECTING is the actual leak window — the WG iface is gone but the
    user hasn't given up yet. The switch must engage there, not only on FAILED."""
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.RECONNECTING)
    fake_plat.engage_kill_switch.assert_called_once_with(["203.0.113.42"])


def test_kill_switch_releases_on_connected(tmp_path):
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    mgr = _mgr_with_bypass(TunnelState.RECONNECTING, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.CONNECTED)
    fake_plat.release_kill_switch.assert_called_once()
    fake_plat.engage_kill_switch.assert_not_called()


def test_kill_switch_releases_on_clean_disconnected(tmp_path):
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    mgr = _mgr_with_bypass(TunnelState.FAILED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.DISCONNECTED)
    fake_plat.release_kill_switch.assert_called_once()


def test_kill_switch_disabled_does_not_engage(tmp_path):
    """Default off — state changes must not touch the firewall."""
    fake_plat = MagicMock()
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.FAILED)
    fake_plat.engage_kill_switch.assert_not_called()
    fake_plat.release_kill_switch.assert_not_called()


def test_kill_switch_refuses_to_engage_without_bypass_ips(tmp_path):
    """A profile without bypass_ips would mean the user has no recovery path
    once we engage. Refuse and log instead of locking them out."""
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, [])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api._on_state_change(TunnelState.FAILED)
    fake_plat.engage_kill_switch.assert_not_called()


def test_set_kill_switch_off_releases_immediately(tmp_path):
    """Disabling the toggle should always release any stale rule, even when
    we never engaged ourselves (e.g. recovering from a previous session)."""
    fake_plat = MagicMock()
    (tmp_path / "settings.json").write_text(json.dumps({"kill_switch": True}))
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api()
        r = api.set_settings({"kill_switch": False})
    assert r["ok"] is True
    fake_plat.release_kill_switch.assert_called_once()


def test_set_kill_switch_on_engages_now_if_tunnel_is_down(tmp_path):
    """Activating the toggle while the tunnel is already FAILED must engage
    immediately — otherwise the user keeps leaking until the next state change."""
    fake_plat = MagicMock()
    mgr = _mgr_with_bypass(TunnelState.FAILED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        r = api.set_settings({"kill_switch": True})
    assert r["ok"] is True
    fake_plat.engage_kill_switch.assert_called_once_with(["203.0.113.42"])


def test_set_kill_switch_on_no_op_if_tunnel_is_connected(tmp_path):
    """When the tunnel is up, just persist the value — actual engagement
    waits for the next FAILED/RECONNECTING transition."""
    fake_plat = MagicMock()
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        r = api.set_settings({"kill_switch": True})
    assert r["ok"] is True
    fake_plat.engage_kill_switch.assert_not_called()


def test_set_kill_switch_rolls_back_on_platform_error(tmp_path):
    """The Linux path raises PlatformError when enabling. Must surface
    {ok: False, error: ...} and revert the persisted value so the UI doesn't
    show a falsely-active switch."""
    from outwarp.platforms import PlatformError

    fake_plat = MagicMock()
    fake_plat.engage_kill_switch.side_effect = PlatformError(
        "Kill switch is not yet implemented on Linux"
    )
    mgr = _mgr_with_bypass(TunnelState.FAILED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        r = api.set_settings({"kill_switch": True})
    assert r["ok"] is False
    assert "not yet implemented" in r["error"]
    assert r["settings"]["kill_switch"] is False
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["kill_switch"] is False


def test_shutdown_releases_kill_switch(tmp_path):
    """Leaving the rule engaged after the app exits would brick the user's
    network until they figure out where the rule lives."""
    fake_plat = MagicMock()
    mgr = _mgr_with_bypass(TunnelState.CONNECTED, ["203.0.113.42"])
    with (
        patch("outwarp.api.default_config_path",
              return_value=tmp_path / "config.json"),
        patch("outwarp.api.get_platform", return_value=fake_plat),
    ):
        api, _ = _make_api(mgr)
        api.shutdown()
    fake_plat.release_kill_switch.assert_called_once()


# --- phase in status payload ---

def test_get_status_includes_empty_phase_without_manager():
    api, _ = _make_api()
    s = api.get_status()
    assert s["phase"] == ""


def test_get_status_returns_managers_phase():
    mgr = MagicMock()
    mgr.state = TunnelState.CONNECTING
    mgr.config.server.endpoint = "x"
    mgr.config.server.port = 1
    mgr.config.wireguard.tunnel_name = "t"
    mgr.phase = "wg"
    api, _ = _make_api(mgr)
    s = api.get_status()
    assert s["phase"] == "wg"


def test_get_status_coerces_non_string_phase_to_empty():
    """Defence in depth — if a future bug stuffs a non-string into phase, the
    bridge serialiser shouldn't blow up. Coerce to empty string instead."""
    mgr = MagicMock()
    mgr.state = TunnelState.CONNECTING
    mgr.config.server.endpoint = "x"
    mgr.config.server.port = 1
    mgr.config.wireguard.tunnel_name = "t"
    mgr.phase = 12345  # nonsense
    api, _ = _make_api(mgr)
    s = api.get_status()
    assert s["phase"] == ""


# --- About: get_app_info / open_url ---

def test_get_app_info_returns_metadata():
    api, _ = _make_api()
    info = api.get_app_info()
    assert isinstance(info["version"], str) and info["version"]
    assert isinstance(info["python"], str) and info["python"]
    assert isinstance(info["platform"], str) and info["platform"]
    assert info["repo_url"].startswith("https://github.com/")
    assert info["license"] == "MIT"
    names = {p["name"] for p in info["third_party"]}
    # Each component the README and CLAUDE.md call out should be in the list.
    assert {"wstunnel", "WireGuard", "pystray", "pywebview"} <= names
    for p in info["third_party"]:
        assert p["url"].startswith("https://")
        assert p["license"]  # non-empty


def test_open_url_invokes_webbrowser():
    api, _ = _make_api()
    with patch("webbrowser.open") as opener:
        r = api.open_url("https://example.com/x")
    assert r == {"ok": True}
    opener.assert_called_once_with("https://example.com/x", new=2)


def test_open_url_allows_plain_http():
    """Some self-hosted resources (status pages, CI dashboards) only serve
    over HTTP. Allow it; refuse only schemes that can launch local handlers."""
    api, _ = _make_api()
    with patch("webbrowser.open") as opener:
        r = api.open_url("http://example.com/")
    assert r["ok"] is True
    opener.assert_called_once()


def test_open_url_refuses_non_http_schemes():
    """A compromised renderer must not be able to launch file://, javascript:
    or custom protocol handlers via the bridge."""
    api, _ = _make_api()
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "outwarp://x", ""):
        with patch("webbrowser.open") as opener:
            r = api.open_url(bad)
        assert r["ok"] is False
        opener.assert_not_called()


def test_open_url_refuses_non_string_input():
    api, _ = _make_api()
    for bad in (None, 42, ["https://x"], {"url": "https://x"}):
        with patch("webbrowser.open") as opener:
            r = api.open_url(bad)  # type: ignore[arg-type]
        assert r["ok"] is False
        opener.assert_not_called()


def test_open_url_surfaces_browser_failure():
    api, _ = _make_api()
    with patch("webbrowser.open", side_effect=RuntimeError("no display")):
        r = api.open_url("https://example.com/")
    assert r["ok"] is False
    assert "no display" in r["error"]


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
    api._stop_latency_loop()


def test_default_stats_include_latency_and_location_keys():
    api, _ = _make_api()
    assert api._stats["latency_ms"] == 0
    assert api._stats["exit_location"] == ""


def test_disconnect_resets_latency_and_location(tmp_path):
    cfg = _real_config(tmp_path)
    mgr = _mgr_with_config(cfg, state=TunnelState.DISCONNECTED)
    api, _ = _make_api(mgr)
    api._stats["latency_ms"] = 42
    api._stats["exit_location"] = "Madrid, Spain"
    api._stats["exit_ip"] = "1.2.3.4"
    api._on_state_change(TunnelState.DISCONNECTED)
    assert api._stats["latency_ms"] == 0
    assert api._stats["exit_location"] == ""
    assert api._stats["exit_ip"] == ""


def test_start_latency_loop_noop_without_manager():
    api, _ = _make_api()
    api._start_latency_loop()
    assert api._latency_thread is None


def test_start_latency_loop_starts_thread_with_manager(tmp_path):
    cfg = _real_config(tmp_path)
    mgr = _mgr_with_config(cfg, state=TunnelState.CONNECTED)
    api, _ = _make_api(mgr)
    with patch("outwarp.network.measure_latency_ms", return_value=17):
        api._start_latency_loop()
        try:
            import time
            # Wait briefly for the loop to take its first sample.
            for _ in range(50):
                if api._stats["latency_ms"] == 17:
                    break
                time.sleep(0.01)
            assert api._stats["latency_ms"] == 17
        finally:
            api._stop_latency_loop()


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


# ── updates ─────────────────────────────────────────────────────────────────

# Patching outwarp.api.sys.platform mutates the real sys module, which
# platformdirs reads during Api() construction — so build the Api first, then
# patch only around the call under test. Keeps these tests OS-independent.

@patch("outwarp.api.updater.check_for_update", return_value={"available": True, "latest": "9.9.9"})
def test_check_for_updates_windows_passes_through(_mock):
    api, _ = _make_api()
    with patch("outwarp.api.sys.platform", "win32"):
        r = api.check_for_updates()
    assert r == {"available": True, "latest": "9.9.9"}
    assert "manual" not in r


@patch("outwarp.api.updater.check_for_update", return_value={"available": True, "latest": "9.9.9"})
def test_check_for_updates_linux_adds_manual_command(_mock):
    api, _ = _make_api()
    with patch("outwarp.api.sys.platform", "linux"):
        r = api.check_for_updates()
    assert r["manual"] is True
    assert "install.sh" in r["command"]


def test_apply_update_linux_returns_manual():
    api, _ = _make_api()
    with patch("outwarp.api.sys.platform", "linux"):
        r = api.apply_update()
    assert r["ok"] is False
    assert r["manual"] is True
    assert "install.sh" in r["command"]


def test_apply_update_windows_dispatches_background_thread():
    api, _ = _make_api()
    with patch("outwarp.api.sys.platform", "win32"), \
         patch("outwarp.api.threading.Thread") as mock_thread:
        r = api.apply_update()
    assert r == {"ok": True}
    mock_thread.assert_called_once()
    assert mock_thread.call_args.kwargs["target"] == api._run_update


@patch("outwarp.api.updater.check_for_update", return_value={"available": False, "latest": "0.1.4"})
def test_run_update_emits_current_when_up_to_date(_mock):
    api, _ = _make_api()
    api._emit = MagicMock()
    api._run_update()
    phases = [c.args[1]["phase"] for c in api._emit.call_args_list]
    assert phases[0] == "checking"
    assert "current" in phases


@patch("outwarp.api.updater.download_installer")
@patch(
    "outwarp.api.updater.check_for_update",
    return_value={
        "available": True, "latest": "9.9.9",
        "asset_url": "https://x/OutWarpSetup-9.9.9.exe",
        "asset_name": "OutWarpSetup-9.9.9.exe",
    },
)
def test_run_update_downloads_launches_and_quits(_mock_check, mock_dl):
    api, _ = _make_api()
    api._emit = MagicMock()
    api._launch_installer = MagicMock(return_value=True)
    api._quit_for_update = MagicMock()
    api._run_update()
    mock_dl.assert_called_once()
    api._launch_installer.assert_called_once()
    api._quit_for_update.assert_called_once()
    phases = [c.args[1]["phase"] for c in api._emit.call_args_list]
    assert "applying" in phases


@patch("outwarp.api.updater.download_installer")
@patch(
    "outwarp.api.updater.check_for_update",
    return_value={
        "available": True, "latest": "9.9.9",
        "asset_url": "https://x/OutWarpSetup-9.9.9.exe",
        "asset_name": "OutWarpSetup-9.9.9.exe",
    },
)
def test_run_update_does_not_quit_if_installer_launch_fails(_mock_check, _mock_dl):
    api, _ = _make_api()
    api._emit = MagicMock()
    api._launch_installer = MagicMock(return_value=False)
    api._quit_for_update = MagicMock()
    api._run_update()
    api._quit_for_update.assert_not_called()
    phases = [c.args[1]["phase"] for c in api._emit.call_args_list]
    assert phases[-1] == "error"
