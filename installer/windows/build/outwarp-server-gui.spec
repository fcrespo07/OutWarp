# PyInstaller spec for the OutWarp server GUI (Windows).
#
# Mode: one-folder, GUI (no console).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent.parent
SERVER_PKG = ROOT / "server" / "outwarp_server"
ICON_PATH = SERVER_PKG / "resources" / "app_icon.ico"
VERSION_FILE = ROOT / "installer" / "windows" / "build" / "version_info_server.txt"

sys.path.insert(0, str(ROOT / "server"))

datas = [
    (str(SERVER_PKG / "ui"), "ui"),
    (str(SERVER_PKG / "resources"), "resources"),
]

# pystray and pywebview pick their OS backend at runtime via dynamic
# imports that PyInstaller's static analysis misses, so collect every
# submodule explicitly.
hiddenimports = [
    *collect_submodules("pystray"),
    *collect_submodules("webview"),
    "PIL.Image",
    "PIL.ImageDraw",
    "cryptography.hazmat.backends.openssl",
]

a = Analysis(
    [str(SERVER_PKG / "server_app.py")],
    pathex=[str(ROOT / "server")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="outwarp-server-gui",
)
