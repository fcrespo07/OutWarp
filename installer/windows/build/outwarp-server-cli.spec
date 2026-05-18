# PyInstaller spec for the OutWarp server CLI (Windows).
#
# Console subsystem — must be runnable from cmd / PowerShell.
# Mode: one-folder so it can share assets with the GUI build via the
# installer layout.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent.parent
SERVER_PKG = ROOT / "server" / "outwarp_server"
ICON_PATH = SERVER_PKG / "resources" / "app_icon.ico"
VERSION_FILE = ROOT / "installer" / "windows" / "build" / "version_info_server.txt"

sys.path.insert(0, str(ROOT / "server"))

datas = [
    (str(SERVER_PKG / "resources"), "resources"),
]

hiddenimports = [
    "cryptography.hazmat.backends.openssl",
]

a = Analysis(
    [str(SERVER_PKG / "cli.py")],
    pathex=[str(ROOT / "server")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "webview", "pystray",
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
    name="outwarp-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="outwarp-server-cli",
)
