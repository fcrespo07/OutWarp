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
from outwarp.tui.screens.profile import ProfileScreen


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
            "client_private_key": "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
            "server_public_key": "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
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
    # platformdirs honours XDG_* only on Linux; on Windows it resolves to the
    # real %APPDATA%, so the env vars above don't isolate the config dir and the
    # app would read (and other tests would leak into) real user state. Patch
    # the resolver the app actually calls so "no profile" holds on every OS.
    monkeypatch.setattr(
        "outwarp.tui.app.default_config_path", lambda: tmp_path / "config.json",
    )
    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, EmptyScreen)
        await pilot.press("i")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ImportModal)


@pytest.mark.asyncio
async def test_import_modal_notifies_with_the_signature_verdict(
    tmp_path: Path, monkeypatch,
) -> None:
    """A successful import used to dismiss silently — the signature verdict
    (unsigned / verified / rotated key) only ever reached a log line."""
    from textual.widgets import Input

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(
        "outwarp.tui.app.default_config_path", lambda: tmp_path / "config.json",
    )
    owcfg_path = _write_owcfg(tmp_path)

    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause(0.2)
        modal = app.screen
        assert isinstance(modal, ImportModal)

        notified: dict = {}
        monkeypatch.setattr(
            modal, "notify",
            lambda message, **kw: notified.update(message=message, **kw),
        )
        modal.query_one("#path", Input).value = str(owcfg_path)
        modal.action_submit()
        await pilot.pause(0.2)

    assert notified.get("severity") == "warning"  # _write_owcfg's profile is unsigned
    assert notified.get("message")


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


def test_start_manager_threads_kill_switch_setting_through(
    tmp_path: Path, monkeypatch,
) -> None:
    """CONCEPTO-E / FIX-06b: the TUI's TunnelManager must honour a
    kill_switch=True the user set via the (shared) settings.json — e.g. from
    the pywebview GUI — even though the TUI has no kill-switch toggle of its
    own yet. Before this, kill_switch was silently dead everywhere except
    outwarp.api.Api."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from outwarp.config import ClientConfig, default_config_path, import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    from unittest.mock import MagicMock, patch
    captured_kwargs = {}

    def _fake_manager(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    settings = {
        "auto_connect": False, "allow_tls_intercept": False,
        "auto_reconnect": True, "kill_switch": True,
    }

    app = OutWarpClientTUI()
    app.config = ClientConfig.load(default_config_path())

    with patch("outwarp.tui.app.TunnelManager", _fake_manager), \
         patch("outwarp.tui.app.load_settings", return_value=settings), \
         patch.object(app, "_push_unique"):
        app.start_manager(auto=True)

    assert captured_kwargs["kill_switch_enabled"] is True


def test_on_mount_releases_stale_kill_switch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from unittest.mock import patch

    app = OutWarpClientTUI()
    with (
        patch("outwarp.tui.app.setup_logging"),
        patch("outwarp.tui.app.release_stale_async") as released,
        patch.object(app, "reload_config"),
    ):
        app.on_mount()
    released.assert_called_once()


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


# ─── ProfileScreen ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_screen_saves_valid_edit(tmp_path: Path, monkeypatch) -> None:
    """The save action must run inputs through apply_profile_patch, persist
    the new config.json, snapshot the pre-edit state as config.original.json,
    and ask the app to rebuild its TunnelManager with the fresh config."""
    from unittest.mock import MagicMock, patch

    from textual.widgets import Input

    from outwarp.config import (
        ClientConfig,
        default_config_path,
        import_owcfg,
        original_config_path,
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    import_owcfg(_write_owcfg(tmp_path))

    # Strip the original snapshot import_owcfg writes so we can prove that
    # ProfileScreen.action_save takes its own snapshot on first edit. (Without
    # this, the snapshot path would already exist and we couldn't tell which
    # write produced it.)
    original_config_path(default_config_path()).unlink()

    # TunnelManager is patched so start_manager() doesn't hit wstunnel; the
    # MagicMock still satisfies the listener/start_manager contract.
    with patch("outwarp.tui.app.TunnelManager", return_value=MagicMock()):
        app = OutWarpClientTUI()
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.push_screen("profile")
            await pilot.pause(0.2)
            assert isinstance(app.screen, ProfileScreen)

            app.screen.query_one("#field-mtu", Input).value = "1400"
            app.screen.query_one("#field-dns", Input).value = "9.9.9.9, 1.1.1.1"

            with patch.object(app, "start_manager") as restart:
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)
                restart.assert_called_once()

            saved = ClientConfig.load(default_config_path())
            assert saved.wireguard.mtu == 1400
            assert saved.wireguard.dns == ["9.9.9.9", "1.1.1.1"]
            # First-edit snapshot must now exist with the *pre-edit* values
            # (MTU 1380 from the imported owcfg), so a later reset restores
            # them — not the post-edit state.
            orig = ClientConfig.load(original_config_path(default_config_path()))
            assert orig.wireguard.mtu == 1380


@pytest.mark.asyncio
async def test_profile_screen_surfaces_validation_error(
    tmp_path: Path, monkeypatch,
) -> None:
    """An out-of-range MTU must not crash the screen — the ConfigError that
    apply_profile_patch raises lands in the status line so the user can fix it."""
    from unittest.mock import MagicMock, patch

    from textual.widgets import Input, Static

    from outwarp.config import ClientConfig, default_config_path, import_owcfg

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    import_owcfg(_write_owcfg(tmp_path))

    with patch("outwarp.tui.app.TunnelManager", return_value=MagicMock()):
        app = OutWarpClientTUI()
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.push_screen("profile")
            await pilot.pause(0.2)

            app.screen.query_one("#field-mtu", Input).value = "200"  # below 576

            with patch.object(app, "start_manager") as restart:
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)
                restart.assert_not_called()

            status = app.screen.query_one("#profile-status", Static)
            # The renderable carries the Spanish error from apply_profile_patch.
            rendered = status.render() if hasattr(status, "render") else status._renderable
            assert "MTU" in str(rendered)
            # The on-disk config must be untouched.
            saved = ClientConfig.load(default_config_path())
            assert saved.wireguard.mtu == 1380


@pytest.mark.asyncio
async def test_profile_screen_reset_restores_original_snapshot(
    tmp_path: Path, monkeypatch,
) -> None:
    """Pressing R reloads config.original.json into config.json so the user
    walks back every local edit in one step."""
    from unittest.mock import MagicMock, patch

    from outwarp.config import (
        ClientConfig,
        apply_profile_patch,
        default_config_path,
        import_owcfg,
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    import_owcfg(_write_owcfg(tmp_path))

    # Pre-edit the live config so reset has something meaningful to undo —
    # the snapshot was captured at import time with MTU 1380.
    edited = apply_profile_patch(
        ClientConfig.load(default_config_path()),
        {"mtu": 1400},
    )
    edited.save(default_config_path())

    with patch("outwarp.tui.app.TunnelManager", return_value=MagicMock()):
        app = OutWarpClientTUI()
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.push_screen("profile")
            await pilot.pause(0.2)

            with patch.object(app, "start_manager"):
                await pilot.press("r")
                await pilot.pause(0.2)

            restored = ClientConfig.load(default_config_path())
            assert restored.wireguard.mtu == 1380


@pytest.mark.asyncio
async def test_k_on_dashboard_disconnects_without_quitting() -> None:
    """B-032: 'k' used to stop the tunnel and then exit the whole TUI."""
    from unittest.mock import MagicMock, PropertyMock, patch

    from outwarp.tui.screens.dashboard import DashboardScreen

    app = MagicMock(service_managed=False)
    screen = DashboardScreen.__new__(DashboardScreen)
    with patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app), \
         patch.object(DashboardScreen, "notify") as notify:
        await screen._async_disconnect()

    app.manager.stop.assert_called_once()
    app.exit.assert_not_called()
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_k_on_connecting_cancels_and_returns_to_dashboard() -> None:
    from unittest.mock import MagicMock, PropertyMock, patch

    from outwarp.tui.screens.connecting import ConnectingScreen

    app = MagicMock()
    screen = ConnectingScreen.__new__(ConnectingScreen)
    with patch.object(ConnectingScreen, "app", new_callable=PropertyMock, return_value=app):
        await screen._async_cancel()

    app.manager.stop.assert_called_once()
    app.show_disconnected.assert_called_once()
    app.exit.assert_not_called()


def _route(running: bool):
    from unittest.mock import PropertyMock, patch

    from outwarp.tunnel import TunnelState

    app = OutWarpClientTUI()
    with patch.object(app, "_push_unique") as push, \
         patch.object(app, "_notify_state"), \
         patch.object(OutWarpClientTUI, "is_running", new_callable=PropertyMock,
                      return_value=running):
        app._route_state(TunnelState.CONNECTING)
        app._route_state(TunnelState.DISCONNECTED)
    return push


def test_disconnected_state_routes_to_dashboard() -> None:
    assert _route(running=True).call_args_list[-1].args == ("dashboard",)


def test_disconnect_during_shutdown_does_not_push_a_screen() -> None:
    # Quitting stops the manager; the DISCONNECTED it reports arrives after the
    # screens are gone.
    assert _route(running=False).call_args_list[-1].args == ("connecting",)
