from __future__ import annotations

from unittest.mock import MagicMock

from PIL import Image

from outwarp.i18n import t
from outwarp.tray import (
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
    assert fake_icon.title == _x11_safe_title(t("tray.state.connected", tray._lang()))
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


def test_tray_profile_submenu_lists_profiles_and_switches(monkeypatch) -> None:
    import sys
    import threading
    import types

    class _Item:
        def __init__(self, text, action, checked=None, radio=False):
            self.text, self.action, self.radio = text, action, radio
            self.checked = checked(self) if checked else None

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(MenuItem=_Item))
    api = MagicMock()
    api.list_profiles.return_value = [
        {"id": "casa", "name": "Casa", "active": True},
        {"id": "trabajo", "name": "Trabajo", "active": False},
    ]
    tray = TrayApp(manager=None, on_show=lambda: None, on_quit=lambda: None, api=api)
    items = list(tray._profile_items())
    assert [i.text for i in items] == ["Casa", "Trabajo"]
    assert [i.checked for i in items] == [True, False]
    assert all(i.radio for i in items)

    ran = threading.Event()
    api.set_active_profile.side_effect = lambda pid: ran.set()
    items[1].action(None, None)
    assert ran.wait(2)
    api.set_active_profile.assert_called_once_with("trabajo")


def test_tray_follows_the_last_profile_being_removed() -> None:
    tray = TrayApp(manager=MagicMock(), on_show=lambda: None, on_quit=lambda: None)
    tray._icon = MagicMock()
    tray.update_manager(None)
    assert tray._manager is None
    assert "OutWarp" in tray._icon.title
