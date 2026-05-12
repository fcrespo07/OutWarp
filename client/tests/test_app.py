from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


class TestSingleInstanceLock:
    def test_acquire_and_release(self) -> None:
        from warpsocket.app import _SingleInstanceLock
        lock = _SingleInstanceLock()
        assert lock.acquire() is True
        lock.release()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only flock test")
    def test_double_acquire_posix(self) -> None:
        from warpsocket.app import _SingleInstanceLock
        lock1 = _SingleInstanceLock()
        lock2 = _SingleInstanceLock()
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mutex test")
    def test_double_acquire_windows(self) -> None:
        from warpsocket.app import _SingleInstanceLock
        lock1 = _SingleInstanceLock()
        lock2 = _SingleInstanceLock()
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_release_without_acquire_is_safe(self) -> None:
        from warpsocket.app import _SingleInstanceLock
        lock = _SingleInstanceLock()
        lock.release()  # must not raise


class TestMainEntryPoint:
    def test_returns_one_when_lock_already_held(self) -> None:
        from warpsocket.app import _SingleInstanceLock, main
        with patch.object(_SingleInstanceLock, "acquire", return_value=False):
            assert main() == 1

    def test_orchestrates_without_config(self, tmp_path) -> None:
        """main() with no config should start uvicorn + tray + pywebview.

        We mock the three side-effecting subsystems so the test exercises the
        wiring (token generation, manager_ref initialization, on_quit shutdown)
        without actually starting a server or opening a window.
        """
        from warpsocket import app as app_mod

        # No on-disk config → manager_ref starts as [None].
        nonexistent = tmp_path / "no" / "config.json"

        captured = {}

        def fake_start(api_app, port, token, **kwargs):
            captured["port"] = port
            captured["token"] = token

            class _Session:
                def run(self, title):
                    captured["title"] = title

                def shutdown(self):
                    captured["shutdown"] = True

            return _Session()

        class _FakeTrayApp:
            def __init__(self, manager, on_show, on_quit):
                captured["tray_manager"] = manager
                captured["on_show"] = on_show
                captured["on_quit"] = on_quit

            def run(self):
                captured["tray_ran"] = True

            def stop(self):
                captured["tray_stopped"] = True

            def update_manager(self, m):
                captured["tray_manager_updated"] = m

        with (
            patch("warpsocket.app.default_config_path", return_value=nonexistent),
            patch("warpsocket.webview.start", side_effect=fake_start),
            patch("warpsocket.tray.TrayApp", _FakeTrayApp),
        ):
            rc = app_mod.main()

        assert rc == 0
        assert captured["port"] == 7171
        assert isinstance(captured["token"], str) and len(captured["token"]) >= 32
        assert captured["tray_manager"] is None
        assert captured["tray_ran"] is True
        assert captured["title"] == "WarpSocket"
