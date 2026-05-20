from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from outwarp_server import binaries


def test_find_wg_prefers_path():
    with patch("outwarp_server.binaries.shutil.which", return_value="/usr/bin/wg"):
        assert binaries.find_wg() == Path("/usr/bin/wg")


def test_find_wg_windows_fallback(tmp_path):
    fake = tmp_path / "wg.exe"
    fake.write_text("x")
    with patch("outwarp_server.binaries.shutil.which", return_value=None), \
         patch("outwarp_server.binaries.sys.platform", "win32"), \
         patch("outwarp_server.binaries._WIN_WG_PATHS", (str(fake),)):
        assert binaries.find_wg() == fake


def test_find_wg_none_when_missing():
    with patch("outwarp_server.binaries.shutil.which", return_value=None), \
         patch("outwarp_server.binaries._POSIX_WG_PATHS", ()), \
         patch("outwarp_server.binaries._WIN_WG_PATHS", ()):
        assert binaries.find_wg() is None


def test_find_wstunnel_uses_path_when_not_frozen():
    # _frozen_dirs() is empty unless sys.frozen is set, so this hits PATH.
    with patch("outwarp_server.binaries.shutil.which", return_value="/usr/bin/wstunnel"):
        assert binaries.find_wstunnel() == Path("/usr/bin/wstunnel")


def test_find_wstunnel_prefers_bundle_dir(tmp_path):
    name = "wstunnel.exe"
    bundled = tmp_path / name
    bundled.write_text("x")
    with patch("outwarp_server.binaries._frozen_dirs", return_value=[tmp_path]), \
         patch("outwarp_server.binaries.sys.platform", "win32"), \
         patch("outwarp_server.binaries.shutil.which", return_value=r"C:\other\wstunnel.exe"):
        assert binaries.find_wstunnel() == bundled
