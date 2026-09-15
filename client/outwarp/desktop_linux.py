"""Linux desktop integration: Wayland/Hyprland specifics the GUI needs to feel
native, verified live on Omarchy (Arch + Hyprland 0.56 + omarchy-shell).

What was found on a real session and is encoded here:

* The pywebview/GTK window's app_id is the Python *script name* unless the
  program name is set before GTK initialises — Hyprland reported
  ``class: win_test.py``. ``GLib.set_prgname("outwarp")`` makes it
  ``outwarp``, which is what a window rule and ``StartupWMClass`` key on.
* Hyprland tiles the window by default (it was forced to 706×860). A window
  rule is the only way to get a floating, centred window; Hyprland ≥ 0.55
  configures in Lua (Omarchy: ``o.window(...)`` in a required module), older
  setups in hyprlang (``windowrulev2 = ...``). Both snippets live here.
* The tray is a StatusNotifierItem: pystray's appindicator backend registers
  fine with omarchy-shell's watcher and the icon/tooltip follow tunnel state
  — but only when the GObject bindings are importable, which a pipx venv
  without system site packages cannot do (then pystray silently falls back
  to the Xorg backend and nothing shows under Wayland).
* Notifications: omarchy-shell's daemon advertises ``icon-static``, so
  ``notify-send -i <png>`` shows the app icon.
* XDG autostart (``~/.config/autostart``) is honoured: uwsm activates
  ``xdg-desktop-autostart.target`` in the Hyprland session.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "outwarp"
_RESOURCES = Path(__file__).parent / "resources"


def icon_path() -> Path:
    return _RESOURCES / "app_icon.png"


def is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def is_hyprland() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or (
        os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "hyprland"
    )


def set_app_id() -> None:
    """Give the GTK window a stable app_id / WM_CLASS. Must run before GTK
    initialises (i.e. before ``webview.start``); harmless elsewhere."""
    if sys.platform != "linux":
        return
    try:
        from gi.repository import GLib

        GLib.set_prgname(APP_ID)
        GLib.set_application_name("OutWarp")
    except Exception as exc:  # gi missing: the GUI cannot start anyway
        log.debug("could not set program name: %s", exc)


# ── tray ───────────────────────────────────────────────────────────────────


def appindicator_available() -> tuple[bool, str]:
    """Can pystray use a StatusNotifierItem backend from this interpreter?"""
    try:
        import gi
    except ImportError:
        return False, "python3-gi (PyGObject) not importable from this venv"
    for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(ns, "0.1")
            __import__("gi.repository", fromlist=[ns])
            return True, ns
        except (ValueError, ImportError):
            continue
    return False, "no AppIndicator GObject typelib (libayatana-appindicator)"


def status_notifier_watcher_present() -> bool | None:
    """Is a StatusNotifierWatcher on the session bus (a bar that hosts SNI
    trays: omarchy-shell, waybar, KDE, GNOME with the AppIndicator
    extension)? None when it cannot be determined (no busctl)."""
    if not shutil.which("busctl"):
        return None
    try:
        out = subprocess.run(
            ["busctl", "--user", "list", "--no-legend"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "org.kde.StatusNotifierWatcher" in out


def tray_status() -> tuple[str, str]:
    """('ok' | 'warn' | 'skip', detail) for the doctor and `outwarp ui`."""
    if sys.platform != "linux":
        return "skip", "not Linux"
    if not (is_wayland() or os.environ.get("DISPLAY")):
        return "skip", "no display session"
    backend_ok, why = appindicator_available()
    watcher = status_notifier_watcher_present()
    if is_wayland() and not backend_ok:
        return "warn", f"Wayland session but no AppIndicator backend: {why}"
    if watcher is False:
        return "warn", "no StatusNotifierWatcher on the session bus (bar without tray support)"
    if backend_ok:
        return "ok", f"{why} + StatusNotifierWatcher{'' if watcher else ' (unverified)'}"
    return "warn", why


# ── Hyprland window rule ───────────────────────────────────────────────────


def hypr_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hypr"


def hyprland_config_kind() -> str | None:
    """'lua' (Hyprland ≥ 0.55 / Omarchy), 'conf' (hyprlang), or None."""
    d = hypr_dir()
    if (d / "hyprland.lua").exists():
        return "lua"
    if (d / "hyprland.conf").exists():
        return "conf"
    return None


LUA_RULE_FILE = "outwarp.lua"
CONF_RULE_FILE = "outwarp.conf"

_LUA_RULE = f'''-- OutWarp: floating, centred window (installed by OutWarp; safe to edit).
o.window("^{APP_ID}$", {{ float = true, center = true, size = {{ 1080, 720 }} }})
'''
_CONF_RULE = f'''# OutWarp: floating, centred window (installed by OutWarp; safe to edit).
windowrulev2 = float, class:^({APP_ID})$
windowrulev2 = center, class:^({APP_ID})$
windowrulev2 = size 1080 720, class:^({APP_ID})$
'''
_LUA_REQUIRE = 'require("hypr.outwarp")'
_CONF_SOURCE = "source = ~/.config/hypr/outwarp.conf"


def hyprland_rule_snippet(kind: str | None = None) -> str:
    kind = kind or hyprland_config_kind() or "lua"
    return _LUA_RULE if kind == "lua" else _CONF_RULE


def hyprland_rule_installed() -> bool:
    d = hypr_dir()
    kind = hyprland_config_kind()
    if kind == "lua":
        main = d / "hyprland.lua"
        return (d / LUA_RULE_FILE).exists() and _contains(main, _LUA_REQUIRE)
    if kind == "conf":
        main = d / "hyprland.conf"
        return (d / CONF_RULE_FILE).exists() and _contains(main, _CONF_SOURCE)
    return False


def _contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8")
    except OSError:
        return False


def install_hyprland_rule() -> str:
    """Write the rule module and hook it into the user's Hyprland config.
    Idempotent; only appends the one require/source line. Returns a
    human-readable summary. Raises OSError on write failure."""
    d = hypr_dir()
    kind = hyprland_config_kind()
    if kind is None:
        raise FileNotFoundError(f"no hyprland.lua or hyprland.conf under {d}")
    if kind == "lua":
        rule_file, main, hook = d / LUA_RULE_FILE, d / "hyprland.lua", _LUA_REQUIRE
    else:
        rule_file, main, hook = d / CONF_RULE_FILE, d / "hyprland.conf", _CONF_SOURCE
    rule_file.write_text(hyprland_rule_snippet(kind), encoding="utf-8")
    if not _contains(main, hook):
        with main.open("a", encoding="utf-8") as fh:
            fh.write(f"\n-- OutWarp window rule\n{hook}\n" if kind == "lua"
                     else f"\n# OutWarp window rule\n{hook}\n")
    return f"wrote {rule_file} and hooked it from {main.name} (reload: hyprctl reload)"
