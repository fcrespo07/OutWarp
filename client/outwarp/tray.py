from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw

from outwarp.tunnel import TunnelManager, TunnelState

log = logging.getLogger(__name__)


def _resources_dir() -> Path:
    """Locate the resources/ directory both in dev and in PyInstaller
    one-folder builds. PyInstaller stores datas at the root of _MEIPASS,
    not inside the module's parent."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "resources"
    return Path(__file__).parent / "resources"


_RESOURCES = _resources_dir()
_BASE_ICON = _RESOURCES / "app_icon.png"

_STATE_COLORS: dict[TunnelState, tuple[int, int, int]] = {
    TunnelState.DISCONNECTED: (128, 128, 128),
    TunnelState.CONNECTING:   (255, 200,   0),
    TunnelState.CONNECTED:    (  0, 200,   0),
    TunnelState.RECONNECTING: (255, 150,   0),
    TunnelState.FAILED:       (220,   0,   0),
}

_STATE_TOOLTIPS: dict[TunnelState, str] = {
    TunnelState.DISCONNECTED: "OutWarp — desconectado",
    TunnelState.CONNECTING:   "OutWarp — conectando...",
    TunnelState.CONNECTED:    "OutWarp — conectado",
    TunnelState.RECONNECTING: "OutWarp — reconectando...",
    TunnelState.FAILED:       "OutWarp — fallo de conexión",
}

_NO_CONFIG_TOOLTIP = "OutWarp — sin configuración"
_NO_CONFIG_DOT = (100, 100, 100)

# English tooltips mirror _STATE_TOOLTIPS. The Spanish dict stays the canonical
# default (the tray defaults to es and the test suite pins it).
_STATE_TOOLTIPS_EN: dict[TunnelState, str] = {
    TunnelState.DISCONNECTED: "OutWarp — disconnected",
    TunnelState.CONNECTING:   "OutWarp — connecting...",
    TunnelState.CONNECTED:    "OutWarp — connected",
    TunnelState.RECONNECTING: "OutWarp — reconnecting...",
    TunnelState.FAILED:       "OutWarp — connection failed",
}
_NO_CONFIG_TOOLTIP_EN = "OutWarp — no configuration"


def _x11_safe_title(text: str) -> str:
    """Strip characters pystray's Xlib backend can't encode in latin-1.

    pystray's ``_xorg`` calls ``window.set_wm_name(self.title)`` which goes
    through ``Xatom.STRING`` (latin-1). Any non-latin-1 char raises
    ``UnicodeEncodeError`` and kills the tray boot, taking the GUI down with it.
    The em-dash (— U+2014) we use as a separator is the typical culprit.

    On Wayland and Windows the title is UTF-8 and this is a no-op (the early
    `encode("latin-1")` succeeds). We only get into the replacement branch on
    X11 with non-ASCII text, so the visual degradation (— → -) is paid only
    where it would otherwise crash.
    """
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        pass
    # Replace the typographic dashes first so we preserve the visual separator.
    fixed = text.replace("—", "-").replace("–", "-")
    return fixed.encode("latin-1", "replace").decode("latin-1")

# Menu labels. Followed live via a lang_getter so the tray tracks the UI's
# language setting (re-read each time the menu opens).
_MENU_STR: dict[str, dict[str, str]] = {
    "es": {
        "open": "Abrir OutWarp", "connect": "Conectar", "disconnect": "Desconectar",
        "reconnect": "Reconectar", "viewlogs": "Ver registro", "quit": "Parar y salir",
    },
    "en": {
        "open": "Open OutWarp", "connect": "Connect", "disconnect": "Disconnect",
        "reconnect": "Reconnect", "viewlogs": "View logs", "quit": "Stop and quit",
    },
}


def load_base_icon() -> Image.Image:
    return Image.open(_BASE_ICON).convert("RGBA")


def icon_for_state(state: TunnelState | None, base: Image.Image) -> Image.Image:
    color = _STATE_COLORS.get(state, _NO_CONFIG_DOT) if state is not None else _NO_CONFIG_DOT
    img = base.copy()
    draw = ImageDraw.Draw(img)
    size = img.width
    dot = size // 3
    margin = size // 16
    box = [size - dot - margin, size - dot - margin, size - margin, size - margin]
    draw.ellipse(box, fill=color, outline=(255, 255, 255), width=max(1, size // 64))
    return img


class TrayApp:
    """System tray icon.

    Left-click (or 'Abrir OutWarp'): brings the pywebview window forward.
    'Parar y salir': full quit — stops tunnel and exits the process.
    """

    def __init__(
        self,
        manager: TunnelManager | None,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        api: object | None = None,
        lang_getter: Callable[[], str] | None = None,
    ) -> None:
        self._manager = manager
        self._on_show = on_show
        self._on_quit = on_quit
        # api drives the connect/disconnect/reconnect/navigate quick actions so
        # they go through the same path (and emit the same events) as the UI.
        self._api = api
        self._lang_getter = lang_getter
        self._icon = None
        self._base = load_base_icon()

        if manager:
            manager.add_listener(self._on_state_change)

    def _lang(self) -> str:
        if self._lang_getter is None:
            return "es"
        try:
            lang = self._lang_getter()
        except Exception:
            return "es"
        return lang if lang in _MENU_STR else "es"

    def _t(self, key: str) -> str:
        return _MENU_STR[self._lang()].get(key, key)

    def _tooltip(self, state: TunnelState | None) -> str:
        if self._lang() == "en":
            if state is None:
                text = _NO_CONFIG_TOOLTIP_EN
            else:
                text = _STATE_TOOLTIPS_EN.get(state, _NO_CONFIG_TOOLTIP_EN)
        else:
            if state is None:
                text = _NO_CONFIG_TOOLTIP
            else:
                text = _STATE_TOOLTIPS.get(state, _NO_CONFIG_TOOLTIP)
        return _x11_safe_title(text)

    def _is_active(self) -> bool:
        st = self._manager.state if self._manager else None
        return st in (
            TunnelState.CONNECTED, TunnelState.CONNECTING, TunnelState.RECONNECTING,
        )

    def _has_profile(self, *_a: object) -> bool:
        return self._manager is not None

    def _toggle_text(self, _item: object) -> str:
        return self._t("disconnect") if self._is_active() else self._t("connect")

    def _toggle_connection(self, icon: object, item: object) -> None:
        if self._api is None:
            return
        try:
            self._api.disconnect() if self._is_active() else self._api.connect()
        except Exception:
            log.exception("tray toggle connection failed")

    def _reconnect(self, icon: object, item: object) -> None:
        if self._api is None:
            return
        try:
            self._api.reconnect()
        except Exception:
            log.exception("tray reconnect failed")

    def _view_logs(self, icon: object, item: object) -> None:
        try:
            self._on_show()
            if self._api is not None:
                self._api.navigate("logs")
        except Exception:
            log.exception("tray view logs failed")

    def update_manager(self, manager: TunnelManager) -> None:
        self._manager = manager
        manager.add_listener(self._on_state_change)

    def _on_state_change(self, state: TunnelState) -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon = icon_for_state(state, self._base)
            self._icon.title = self._tooltip(state)
        except Exception:
            log.exception("Failed to update tray icon for state %s", state)

    def _open_window(self, icon, item) -> None:
        try:
            self._on_show()
        except Exception:
            log.exception("on_show raised")

    def _quit(self, icon, item) -> None:
        if self._icon is not None:
            self._icon.stop()
        try:
            self._on_quit()
        except Exception:
            log.exception("on_quit raised")

    def stop(self) -> None:
        """Stop the tray icon (called during shutdown)."""
        if self._icon is not None:
            with contextlib.suppress(Exception):
                self._icon.stop()

    def run(self) -> None:
        """Start pystray in a background thread (non-blocking)."""
        import pystray

        initial_state = self._manager.state if self._manager else None

        # Text is supplied as callables so the menu reflects the live state
        # (Connect vs Disconnect) and language each time it's opened.
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: self._t("open"),
                self._open_window,
                default=True,  # triggered by left-click on Windows
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._toggle_text, self._toggle_connection, enabled=self._has_profile,
            ),
            pystray.MenuItem(
                lambda item: self._t("reconnect"), self._reconnect, enabled=self._has_profile,
            ),
            pystray.MenuItem(lambda item: self._t("viewlogs"), self._view_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: self._t("quit"), self._quit),
        )

        self._icon = pystray.Icon(
            name="outwarp",
            icon=icon_for_state(initial_state, self._base),
            title=self._tooltip(initial_state),
            menu=menu,
        )
        self._icon.run_detached()
