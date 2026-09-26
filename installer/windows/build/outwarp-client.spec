# PyInstaller spec for the OutWarp client (Windows).
#
# Produces both executables in one one-folder bundle sharing one _internal/,
# the same layout as the server (outwarp-server.spec):
#
#   dist/outwarp-client/
#   ├── outwarp-gui.exe   GUI subsystem, elevates itself: the tray app
#   ├── outwarp.exe       console CLI (`outwarp status`, `outwarp connect`, ...)
#   └── _internal/…
#
# Until 0.15.0 `outwarp.exe` was the GUI and ignored its arguments (B-027).
# A bare `outwarp.exe` still opens the GUI, so old shortcuts keep working.
#
# Mode: one-folder (LGPL of pystray prohibits one-file — the user must
# be able to swap the lib without rebuilding).
#
# Build with:
#     pyinstaller --noconfirm installer/windows/build/outwarp-client.spec
# Invoked indirectly by installer/windows/build/build.py.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent.parent  # repo root
CLIENT_PKG = ROOT / "client" / "outwarp"
ICON_PATH = CLIENT_PKG / "resources" / "app_icon.ico"
VERSION_FILE = ROOT / "installer" / "windows" / "build" / "version_info_client.txt"

sys.path.insert(0, str(ROOT / "client"))

datas = [
    (str(CLIENT_PKG / "ui"), "ui"),
    (str(CLIENT_PKG / "resources"), "resources"),
]

# pystray and pywebview pick their OS backend at runtime via dynamic
# imports that PyInstaller's static analysis misses, so collect every
# submodule explicitly. PIL and webview backends pulled in too.
hiddenimports = [
    *collect_submodules("pystray"),
    *collect_submodules("webview"),
    "PIL.Image",
    "PIL.ImageDraw",
]

_excludes = [
    "tkinter",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pytest", "unittest",
]

a_gui = Analysis(
    [str(CLIENT_PKG / "gui_main.py")],
    pathex=[str(ROOT / "client")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)

a_cli = Analysis(
    [str(CLIENT_PKG / "__main__.py")],
    pathex=[str(ROOT / "client")],
    binaries=[],
    datas=[(str(CLIENT_PKG / "resources"), "resources")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=None)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=None)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="outwarp-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                # GUI subsystem — no console window
    disable_windowed_traceback=False,
    icon=str(ICON_PATH),
    version=str(VERSION_FILE),
    uac_admin=True,               # client elevates itself for WireGuard ops
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="outwarp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH),
    version=str(VERSION_FILE),
    # asInvoker: --help, --version and `status` must not force a UAC prompt
    # and a throwaway elevated console, the same choice as outwarp-server.exe.
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
    name="outwarp-client",
)
