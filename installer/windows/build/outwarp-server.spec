# PyInstaller spec for the OutWarp server (Windows).
#
# Produces BOTH executables in a single one-folder bundle that shares one
# _internal/:
#
#   dist/outwarp-server/
#   ├── outwarp-server-gui.exe   (GUI subsystem — the default, no console)
#   ├── outwarp-server.exe       (console CLI — dormant until enabled in the UI)
#   └── _internal/…              (shared Python runtime + ui/ + resources/)
#
# Shipping both exes from one COLLECT (instead of two separate one-folder
# builds merged by the installer) avoids the fragile _internal collision the
# old two-spec layout produced. The GUI is what the user runs; the CLI exe
# travels alongside but is only reachable from a terminal once the user adds
# {app}\server to PATH via Settings → "Enable command-line interface".

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent.parent
SERVER_PKG = ROOT / "server" / "outwarp_server"
ICON_PATH = SERVER_PKG / "resources" / "app_icon.ico"
VERSION_FILE = ROOT / "installer" / "windows" / "build" / "version_info_server.txt"

sys.path.insert(0, str(ROOT / "server"))

# pystray and pywebview pick their OS backend at runtime via dynamic imports
# that PyInstaller's static analysis misses, so collect every submodule
# explicitly. The CLI doesn't import them, but they live in the shared folder
# (pulled in by the GUI analysis) which is harmless.
_gui_hiddenimports = [
    *collect_submodules("pystray"),
    *collect_submodules("webview"),
    "PIL.Image",
    "PIL.ImageDraw",
    "cryptography.hazmat.backends.openssl",
]
_cli_hiddenimports = [
    "cryptography.hazmat.backends.openssl",
]

a_gui = Analysis(
    [str(SERVER_PKG / "server_app.py")],
    pathex=[str(ROOT / "server")],
    binaries=[],
    datas=[
        (str(SERVER_PKG / "ui"), "ui"),
        (str(SERVER_PKG / "resources"), "resources"),
    ],
    hiddenimports=_gui_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "unittest",
    ],
    noarchive=False,
)

# Entry point must be __main__.py (it calls sys.exit(main())); cli.py has no
# __main__ guard, so pointing PyInstaller at it builds an exe that imports the
# module and exits 0 without ever parsing argv.
a_cli = Analysis(
    [str(SERVER_PKG / "__main__.py")],
    pathex=[str(ROOT / "server")],
    binaries=[],
    datas=[
        (str(SERVER_PKG / "resources"), "resources"),
    ],
    hiddenimports=_cli_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "webview", "pystray",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "unittest",
    ],
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=None)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=None)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="outwarp-server-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH),
    version=str(VERSION_FILE),
    uac_admin=True,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="outwarp-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH),
    version=str(VERSION_FILE),
    # asInvoker (NOT uac_admin): a console CLI must show --help / --version and
    # run read-only subcommands without forcing a UAC prompt + a throwaway
    # elevated console. cli.py's _require_root prints a friendly "run as admin"
    # message for the subcommands that actually touch privileged state.
    uac_admin=False,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="outwarp-server",
)
