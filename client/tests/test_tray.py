from __future__ import annotations

from unittest.mock import MagicMock

from PIL import Image

from warpsocket.tray import (
    _STATE_TOOLTIPS,
    TrayApp,
    icon_for_state,
    load_base_icon,
)
from warpsocket.tunnel import TunnelState


def test_load_base_icon_returns_rgba_image() -> None:
    img = load_base_icon()
    assert isinstance(img, Image.Image)
    assert img.mode == "RGBA"


def test_icon_for_state_handles_all_states() -> None:
    base = load_base_icon()
    for state in TunnelState:
        img = icon_for_state(state, base)
        assert isinstance(img, Image.Image)
        assert img.size == base.size


def test_icon_for_state_differs_per_state() -> None:
    base = load_base_icon()
    seen: set[bytes] = set()
    for state in TunnelState:
        seen.add(icon_for_state(state, base).tobytes())
    assert len(seen) == len(TunnelState)


def test_tray_subscribes_to_manager_on_construction() -> None:
    manager = MagicMock()
    manager.state = TunnelState.DISCONNECTED
    TrayApp(manager=manager, on_show=lambda: None, on_quit=lambda: None)
    manager.add_listener.assert_called_once()


def test_tray_state_change_updates_icon() -> None:
    manager = MagicMock()
    manager.state = TunnelState.DISCONNECTED
    tray = TrayApp(manager=manager, on_show=lambda: None, on_quit=lambda: None)
    fake_icon = MagicMock()
    tray._icon = fake_icon

    tray._on_state_change(TunnelState.CONNECTED)

    assert fake_icon.icon is not None
    assert fake_icon.title == _STATE_TOOLTIPS[TunnelState.CONNECTED]


def test_tray_state_change_noop_before_run() -> None:
    manager = MagicMock()
    manager.state = TunnelState.DISCONNECTED
    tray = TrayApp(manager=manager, on_show=lambda: None, on_quit=lambda: None)
    tray._on_state_change(TunnelState.CONNECTED)  # icon is None; must not raise


def test_tray_open_window_invokes_callback() -> None:
    manager = MagicMock()
    manager.state = TunnelState.DISCONNECTED
    on_show = MagicMock()
    tray = TrayApp(manager=manager, on_show=on_show, on_quit=lambda: None)
    tray._open_window(None, None)
    on_show.assert_called_once()


def test_tray_quit_stops_icon_and_invokes_callback() -> None:
    manager = MagicMock()
    manager.state = TunnelState.DISCONNECTED
    on_quit = MagicMock()
    tray = TrayApp(manager=manager, on_show=lambda: None, on_quit=on_quit)
    fake_icon = MagicMock()
    tray._icon = fake_icon

    tray._quit(None, None)

    fake_icon.stop.assert_called_once()
    on_quit.assert_called_once()


def test_tray_update_manager_subscribes_new_listener() -> None:
    tray = TrayApp(manager=None, on_show=lambda: None, on_quit=lambda: None)
    new_manager = MagicMock()
    tray.update_manager(new_manager)
    new_manager.add_listener.assert_called_once()
