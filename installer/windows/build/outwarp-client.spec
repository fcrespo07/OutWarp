# PyInstaller spec for the OutWarp client GUI (Windows).
#
# Mode: one-folder (LGPL of pystray prohibits one-file — the user must
# be able to swap the lib without rebuilding).
#
# Build with:
#     pyinstaller --noconfirm installer/windows/build/outwarp-client.spec
# Invoked indirectly by installer/windows/build/build.py.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent.parent  # repo root
CLIENT_PKG = ROOT / "client" / "outwarp"
ICON_PATH = CLIENT_PKG / "resources" / "app_icon.ico"
VERSION_FILE = ROOT / "installer" / "windows" / "build" / "version_info_client.txt"

sys.path.insert(0, str(ROOT / "client"))

datas = [
    (str(CLIENT_PKG / "ui"), "ui"),
    (str(CLIENT_PKG / "resources"), "resources"),
]

hiddenimports = [
    "pystray._win32",
    "PIL.Image",
    "PIL.ImageDraw",
    "webview.platforms.edgechromium",
]

a = Analysis(
    [str(CLIENT_PKG / "__main__.py")],
    pathex=[str(ROOT / "client")],
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
    name="outwarp",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="outwarp-client",
)
