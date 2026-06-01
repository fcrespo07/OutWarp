from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from outwarp.tui.app import OutWarpClientTUI
from outwarp.tui.modals.import_owcfg import ImportModal
from outwarp.tui.modals.settings import SettingsModal
from outwarp.tui.screens.empty import EmptyScreen
from outwarp.tui.screens.failed import FailedScreen


def _write_owcfg(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "name": "laptop",
        "server": {"endpoint": "vpn.example.com", "port": 443,
                   "http_upgrade_path_prefix": "s3cr3t"},
        "tls": {"cert_fingerprint_sha256": "AB:" * 31 + "AB"},
        "tunnel": {"local_port": 51820, "remote_host": "10.13.13.1",
                   "remote_port": 51820},
        "wireguard": {
            "tunnel_name": "OutWarp", "client_address": "10.13.13.5/32",
            "client_private_key": "priv", "server_public_key": "pub",
            "dns": ["1.1.1.1"], "mtu": 1380,
        },
        "routing": {"bypass_ips": ["203.0.113.42"]},
        "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
    }
    path = tmp_path / "laptop.owcfg"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_empty_state_when_no_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, EmptyScreen)
        await pilot.press("i")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ImportModal)


@pytest.mark.asyncio
async def test_failed_screen_when_wstunnel_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    # Point OUTWARP_WSTUNNEL at a path that does not exist so find_wstunnel
    # raises TunnelError → TUI routes to FailedScreen.
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(tmp_path / "nope"))
    # Import a valid .owcfg first so config exists.
    from outwarp.config import import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, FailedScreen), type(app.screen).__name__


def test_auto_connect_off_keeps_tunnel_disconnected(tmp_path: Path, monkeypatch) -> None:
    """Regression for the dead `auto_connect` toggle: when the user flips it
    off, `start_manager(auto=True)` must construct the TunnelManager but skip
    manager.start() so the TUI lands on the dashboard disconnected. Without
    this, the modal's hint was a lie.

    Unit-level — we exercise ``start_manager`` directly rather than booting the
    full Textual app, because the dashboard's LiveLog widget kicks off a
    tail_follow task that fights pytest-asyncio's teardown.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from outwarp.config import ClientConfig, default_config_path, import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    from unittest.mock import MagicMock, patch
    fake_mgr_instance = MagicMock()
    settings_off = {
        "auto_connect": False, "allow_tls_intercept": False, "auto_reconnect": True,
    }

    app = OutWarpClientTUI()
    app.config = ClientConfig.load(default_config_path())

    with patch("outwarp.tui.app.TunnelManager", return_value=fake_mgr_instance), \
         patch("outwarp.tui.app.load_settings", return_value=settings_off), \
         patch.object(app, "_push_unique") as push:
        app.start_manager(auto=True)

    fake_mgr_instance.start.assert_not_called()
    fake_mgr_instance.add_listener.assert_called_once()
    # Lands on the dashboard, NOT the connecting screen.
    push.assert_called_once_with("dashboard")


def test_auto_connect_on_starts_manager(tmp_path: Path, monkeypatch) -> None:
    """Mirror of the test above for the default-on path: auto_connect=True must
    push the connecting screen and call manager.start()."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from outwarp.config import ClientConfig, default_config_path, import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    from unittest.mock import MagicMock, patch
    fake_mgr_instance = MagicMock()
    settings_on = {
        "auto_connect": True, "allow_tls_intercept": False, "auto_reconnect": True,
    }

    app = OutWarpClientTUI()
    app.config = ClientConfig.load(default_config_path())

    with patch("outwarp.tui.app.TunnelManager", return_value=fake_mgr_instance), \
         patch("outwarp.tui.app.load_settings", return_value=settings_on), \
         patch.object(app, "_push_unique") as push:
        app.start_manager(auto=True)

    fake_mgr_instance.start.assert_called_once()
    push.assert_called_once_with("connecting")


def test_user_triggered_start_ignores_auto_connect_setting(
    tmp_path: Path, monkeypatch,
) -> None:
    """FailedScreen.action_retry / DashboardScreen.action_reconnect call
    start_manager() with no ``auto`` flag — those are explicit user actions
    and must always start the tunnel even when auto_connect=False."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from outwarp.config import ClientConfig, default_config_path, import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    from unittest.mock import MagicMock, patch
    fake_mgr_instance = MagicMock()
    settings_off = {
        "auto_connect": False, "allow_tls_intercept": False, "auto_reconnect": True,
    }

    app = OutWarpClientTUI()
    app.config = ClientConfig.load(default_config_path())

    with patch("outwarp.tui.app.TunnelManager", return_value=fake_mgr_instance), \
         patch("outwarp.tui.app.load_settings", return_value=settings_off), \
         patch.object(app, "_push_unique"):
        app.start_manager()  # default auto=False

    fake_mgr_instance.start.assert_called_once()


@pytest.mark.asyncio
async def test_settings_modal_persists_tls_intercept(tmp_path: Path, monkeypatch) -> None:
    """Toggling TLS-intercept in the modal writes settings.json and the next
    TunnelManager construction would see it (regression for the school-network
    fix)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("s")
        await pilot.pause(0.2)
        assert isinstance(app.screen, SettingsModal)

        from textual.widgets import Switch
        switch = app.screen.query_one("#switch-allow_tls_intercept", Switch)
        switch.value = True
        await pilot.pause(0.2)

        from outwarp.settings import load_settings
        loaded = load_settings()
        assert loaded["allow_tls_intercept"] is True

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, SettingsModal)
