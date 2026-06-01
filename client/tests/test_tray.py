from __future__ import annotations

from unittest.mock import MagicMock

from PIL import Image

from outwarp.tray import (
    _STATE_TOOLTIPS,
    TrayApp,
    icon_for_state,
    load_base_icon,
)
from outwarp.tunnel import TunnelState


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
    # The title goes through _x11_safe_title before reaching pystray (the Xlib
    # backend rejects non-latin-1 chars and crashes the tray boot — see the
    # docstring on _x11_safe_title). Assert on the post-sanitisation value
    # plus the invariant that the result is latin-1-encodable.
    from outwarp.tray import _x11_safe_title
    assert fake_icon.title == _x11_safe_title(_STATE_TOOLTIPS[TunnelState.CONNECTED])
    fake_icon.title.encode("latin-1")


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


def test_x11_safe_title_strips_emdash() -> None:
    """Regression: pystray Xlib backend raises UnicodeEncodeError on '\\u2014'.

    The school-network reconnect attempt on 2026-05-29 17:10 crashed because
    the tray title contained an em-dash. Sanitisation must replace dashes
    with ASCII '-' and produce a strictly latin-1 string.
    """
    from outwarp.tray import _x11_safe_title

    safe = _x11_safe_title("OutWarp — conectando")
    assert "—" not in safe
    assert safe == "OutWarp - conectando"
    # The actual invariant: pystray must be able to encode this in latin-1.
    safe.encode("latin-1")

    safe2 = _x11_safe_title("OutWarp – reconectando")  # en-dash too
    assert safe2 == "OutWarp - reconectando"

    # ASCII passes through unchanged (avoids unnecessary work in the hot path).
    assert _x11_safe_title("OutWarp connected") == "OutWarp connected"
