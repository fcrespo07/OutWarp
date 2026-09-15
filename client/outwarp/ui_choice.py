"""Which UI the client opens on Linux, and how to add the GUI after the fact.

Linux installs ship the Textual TUI always and the pywebview/GTK window +
tray as the ``gui-linux`` extra. Before this module the choice was made once
by ``install.sh`` (``OUTWARP_CLIENT_GUI=1``) and never revisited: the
launcher ran the TUI, ``outwarp gui`` fell back to the TUI silently, and
adding the GUI later meant knowing the pip extra and the distro packages.

Now the preference lives in ``settings.json`` (``preferred_ui``: ``auto`` /
``gui`` / ``tui``), ``outwarp launch`` (what the .desktop entry runs) resolves
it against what is actually installed, and ``sudo outwarp gui --install``
pulls the GUI stack into an existing install. Windows never reaches the
Linux-only branches: the GUI is always bundled there.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from outwarp.settings import load_settings, save_settings

log = logging.getLogger(__name__)

UiChoice = Literal["auto", "gui", "tui"]
UI_CHOICES: tuple[UiChoice, ...] = ("auto", "gui", "tui")
PREFERRED_UI_KEY = "preferred_ui"

DISTRIBUTION = "outwarp-client"
GUI_EXTRA = "gui-linux"
INSTALL_HINT = "sudo outwarp gui --install"


def desktop_session() -> bool:
    """True inside a graphical session (X11 or Wayland)."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def gui_available() -> tuple[bool, str]:
    """Whether the pywebview window can actually open here.

    On Linux ``import webview`` alone is not enough: pywebview picks its GTK
    backend lazily, so a venv with pywebview but no ``gi``/WebKit2GTK only
    fails at ``webview.start()``. Probe the pieces the window needs.
    """
    try:
        import webview  # noqa: F401 — presence test only
    except ImportError:
        return False, f"pywebview not installed in this venv ({INSTALL_HINT})"
    if sys.platform != "linux":
        return True, "bundled"
    try:
        import gi
    except ImportError:
        return False, f"python3-gi (PyGObject) missing ({INSTALL_HINT})"
    for version in ("4.1", "4.0"):
        try:
            gi.require_version("WebKit2", version)
            gi.require_version("Gtk", "3.0")
        except ValueError:
            continue
        return True, f"pywebview + GTK3 + WebKit2GTK {version}"
    return False, f"WebKit2GTK GObject bindings missing ({INSTALL_HINT})"


def preferred_ui(settings: dict[str, Any] | None = None) -> UiChoice:
    value = (settings or load_settings()).get(PREFERRED_UI_KEY, "auto")
    return value if value in UI_CHOICES else "auto"


def set_preferred_ui(choice: UiChoice) -> None:
    if choice not in UI_CHOICES:
        raise ValueError(f"preferred_ui must be one of {UI_CHOICES}, got {choice!r}")
    settings = load_settings()
    settings[PREFERRED_UI_KEY] = choice
    save_settings(settings)


def resolve_ui(
    settings: dict[str, Any] | None = None,
    *,
    available: bool | None = None,
    desktop: bool | None = None,
) -> Literal["gui", "tui"]:
    """Decide what ``outwarp launch`` opens.

    ``gui`` is honoured only when the stack is installed (otherwise the TUI
    opens and the caller says why); ``auto`` means GUI when installed and a
    display is present, TUI otherwise (SSH, console, headless boxes).
    """
    pref = preferred_ui(settings)
    if available is None:
        available = gui_available()[0]
    if desktop is None:
        desktop = desktop_session()
    if pref == "tui":
        return "tui"
    if pref == "gui":
        return "gui" if available else "tui"
    return "gui" if (available and desktop) else "tui"


# ── adding the GUI to an existing install ──────────────────────────────────

_GUI_PACKAGES: dict[str, list[str]] = {
    "apt": ["python3-gi", "gir1.2-gtk-3.0", "gir1.2-webkit2-4.1",
            "gir1.2-ayatanaappindicator3-0.1", "libnotify-bin"],
    "dnf": ["python3-gobject", "gtk3", "webkit2gtk4.1", "libappindicator-gtk3", "libnotify"],
    "pacman": ["python-gobject", "webkit2gtk-4.1", "libayatana-appindicator", "libnotify"],
    "zypper": ["python3-gobject", "typelib-1_0-WebKit2-4_1", "typelib-1_0-Gtk-3_0",
               "typelib-1_0-AyatanaAppIndicator3-0_1", "libnotify-tools"],
}
_PKG_INSTALL: dict[str, list[str]] = {
    "apt": ["apt-get", "install", "-y"],
    "dnf": ["dnf", "install", "-y"],
    "pacman": ["pacman", "-S", "--needed", "--noconfirm"],
    "zypper": ["zypper", "--non-interactive", "install"],
}


def system_gui_install_command() -> list[str] | None:
    for manager in ("apt", "dnf", "pacman", "zypper"):
        if shutil.which(manager) or (manager == "apt" and shutil.which("apt-get")):
            return [*_PKG_INSTALL[manager], *_GUI_PACKAGES[manager]]
    return None


def gui_extra_requirements() -> list[str]:
    """The pip requirements behind the ``gui-linux`` extra, read from the
    installed distribution so the venv gets exactly what the wheel declares
    (the wheel is not on PyPI, so ``pip install outwarp-client[gui-linux]``
    would not resolve)."""
    from importlib.metadata import PackageNotFoundError, requires

    try:
        reqs = requires(DISTRIBUTION) or []
    except PackageNotFoundError:
        return ["pywebview>=5.0"]
    out: list[str] = []
    for req in reqs:
        if f'extra == "{GUI_EXTRA}"' in req:
            out.append(req.split(";", 1)[0].strip())
    return out or ["pywebview>=5.0"]


def venv_writable() -> bool:
    site = os.path.dirname(os.path.dirname(os.__file__))
    return os.access(sys.prefix, os.W_OK) and os.access(site, os.W_OK)


def enable_system_site_packages(prefix: str | None = None) -> bool:
    """Let this venv import the distro's GObject bindings.

    PyGObject (``gi``) only ships as a system package; pip cannot build it
    into a venv without the whole GTK toolchain. A pipx venv created without
    ``--system-site-packages`` therefore has pywebview but no ``gi`` — the
    window cannot open and pystray falls back to the Xorg backend, which
    shows nothing under Wayland. Flipping the flag in pyvenv.cfg is exactly
    what ``pipx install --system-site-packages`` would have done.
    Returns True when the file now has the flag (changed or already set).
    """
    cfg = Path(prefix or sys.prefix) / "pyvenv.cfg"
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out: list[str] = []
    seen = False
    for line in lines:
        if line.split("=", 1)[0].strip() == "include-system-site-packages":
            out.append("include-system-site-packages = true")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append("include-system-site-packages = true")
    try:
        cfg.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def install_gui(
    *, run: Any = subprocess.run, echo: Any = print,
) -> int:
    """Add the GUI stack to this install: distro packages + the pip extra.

    Runs as the invoking user; the caller checks for root because both the
    package manager and a system-wide pipx venv need it. Returns a shell-style
    exit code and prints what it did so ``outwarp gui --install`` is
    self-explanatory.
    """
    if sys.platform != "linux":
        echo("The GUI is always bundled on this platform.")
        return 0
    if not venv_writable():
        echo(f"This venv ({sys.prefix}) is not writable — run: {INSTALL_HINT}")
        return 2
    sys_cmd = system_gui_install_command()
    if sys_cmd is None:
        echo("Unsupported package manager: install GTK3 + WebKit2GTK GObject "
             "bindings and an AppIndicator library by hand, then re-run.")
        return 2
    echo("Installing system packages: " + " ".join(sys_cmd))
    if run(sys_cmd, check=False).returncode != 0:
        echo("System package install failed — see the package manager output above.")
        return 1
    if enable_system_site_packages():
        echo(f"Enabled system site-packages in {sys.prefix} (for the GObject bindings).")
    pip_cmd = [sys.executable, "-m", "pip", "install", "--quiet",
               "--disable-pip-version-check", *gui_extra_requirements()]
    echo("Installing into the venv: " + " ".join(pip_cmd[4:]))
    if run(pip_cmd, check=False).returncode != 0:
        echo("pip install failed.")
        return 1
    # This interpreter already resolved its sys.path; re-check in a child so
    # the freshly enabled system site-packages are visible.
    probe = run(
        [sys.executable, "-c",
         "from outwarp.ui_choice import gui_available; ok, why = gui_available(); "
         "print(why); raise SystemExit(0 if ok else 1)"],
        check=False,
    )
    if getattr(probe, "returncode", 1) != 0:
        echo("Installed, but the GUI still cannot start — run `outwarp doctor` for details.")
        return 1
    echo("GUI ready. Open it with `outwarp gui`; `outwarp ui gui` makes it the default.")
    return 0


# ── opening the TUI from a launcher ────────────────────────────────────────

_TERMINALS: tuple[tuple[str, list[str]], ...] = (
    # (binary, args before the command). Every one here accepts the command
    # as trailing argv after `-e` (or its own equivalent).
    ("xdg-terminal-exec", []),  # Omarchy sets $TERMINAL to this; takes argv directly
    ("x-terminal-emulator", ["-e"]),
    ("alacritty", ["-e"]),
    ("kitty", ["--"]),
    ("foot", []),
    ("ghostty", ["-e"]),
    ("wezterm", ["start", "--"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]),
    ("tilix", ["-e"]),
    ("xterm", ["-e"]),
)


def terminal_command(argv: Sequence[str]) -> list[str] | None:
    """Wrap ``argv`` in the user's terminal emulator, or None if none found.

    ``$TERMINAL`` wins (Omarchy and most Wayland setups export it), then a
    fixed candidate list. The TUI needs a real tty, so a launcher with
    ``Terminal=false`` has to open one itself.
    """
    term = os.environ.get("TERMINAL")
    if term and shutil.which(term):
        for name, pre in _TERMINALS:
            if os.path.basename(term) == name:
                return [term, *pre, *argv]
        return [term, "-e", *argv]
    for name, pre in _TERMINALS:
        path = shutil.which(name)
        if path:
            return [path, *pre, *argv]
    return None
