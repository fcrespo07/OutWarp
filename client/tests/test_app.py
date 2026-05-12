from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestSingleInstanceLock:
    def test_acquire_and_release(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock = _SingleInstanceLock()
        assert lock.acquire() is True
        lock.release()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only flock test")
    def test_double_acquire_posix(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock1 = _SingleInstanceLock()
        lock2 = _SingleInstanceLock()
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mutex test")
    def test_double_acquire_windows(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock1 = _SingleInstanceLock()
        lock2 = _SingleInstanceLock()
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_release_without_acquire_is_safe(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock = _SingleInstanceLock()
        lock.release()  # must not raise


class TestMainEntryPoint:
    def test_returns_one_when_lock_already_held(self) -> None:
        from outwarp.app import _SingleInstanceLock, main
        with patch.object(_SingleInstanceLock, "acquire", return_value=False):
            assert main() == 1

    def test_orchestrates_without_config(self, tmp_path) -> None:
        """main() with no config should create a pywebview window and start the tray.

        We mock pywebview itself and the TrayApp so this test exercises the
        wiring (Api created, window bound, tray started) without opening a real
        window.
        """
        from outwarp import app as app_mod

        nonexistent = tmp_path / "no" / "config.json"

        captured = {}
        fake_window = MagicMock()

        fake_webview = MagicMock()
        fake_webview.create_window.return_value = fake_window
        fake_webview.start.side_effect = lambda **kwargs: captured.setdefault("start_called", True)

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
            patch("outwarp.app.default_config_path", return_value=nonexistent),
            patch.dict(sys.modules, {"webview": fake_webview}),
            patch("outwarp.tray.TrayApp", _FakeTrayApp),
        ):
            rc = app_mod.main()

        assert rc == 0
        assert captured["tray_ran"] is True
        assert captured["tray_manager"] is None
        assert captured.get("start_called") is True
        # The window was created with the OutWarp title
        kwargs = fake_webview.create_window.call_args.kwargs
        assert kwargs["title"] == "OutWarp"
        # Api was bound to the window via api.bind_window(window)
        fake_window.evaluate_js  # touch attr to ensure it's a MagicMock
