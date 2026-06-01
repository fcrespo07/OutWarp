from __future__ import annotations

import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _unique_lock_args() -> dict[str, str]:
    """Per-test mutex / lock-file names so the suite doesn't collide with a
    real OutWarp client running on the developer's machine."""
    tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    return {
        "mutex_name": f"Local\\OutWarpClient-test-{tag}",
        "lock_file": f"outwarp-client-test-{tag}.lock",
    }


# A minimal but schema-valid .owcfg payload for the tests below. The fingerprint
# is exactly 32 hex octets joined by colons (95 chars) — the strict length the
# config loader enforces.
_VALID_OWCFG = {
    "schema_version": 1,
    "server": {"endpoint": "203.0.113.42", "port": 443,
               "http_upgrade_path_prefix": "x"},
    "tls": {"cert_fingerprint_sha256":
            ("AB:CD:EF:01:23:45:67:89:" * 3) + "AB:CD:EF:01:23:45:67:89"},
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1",
               "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "OutWarp",
        "client_address": "10.0.0.42/32",
        "client_private_key": "dGVzdGtleQ==",
        "server_public_key": "c2VydmVya2V5",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
}


class TestSingleInstanceLock:
    def test_acquire_and_release(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock = _SingleInstanceLock(**_unique_lock_args())
        assert lock.acquire() is True
        lock.release()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only flock test")
    def test_double_acquire_posix(self) -> None:
        from outwarp.app import _SingleInstanceLock
        args = _unique_lock_args()
        lock1 = _SingleInstanceLock(**args)
        lock2 = _SingleInstanceLock(**args)
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mutex test")
    def test_double_acquire_windows(self) -> None:
        from outwarp.app import _SingleInstanceLock
        args = _unique_lock_args()
        lock1 = _SingleInstanceLock(**args)
        lock2 = _SingleInstanceLock(**args)
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_release_without_acquire_is_safe(self) -> None:
        from outwarp.app import _SingleInstanceLock
        lock = _SingleInstanceLock(**_unique_lock_args())
        lock.release()  # must not raise


class TestMainEntryPoint:
    def test_returns_one_when_lock_already_held(self) -> None:
        from outwarp.app import _SingleInstanceLock, main
        with patch.object(_SingleInstanceLock, "acquire", return_value=False):
            assert main() == 1

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only TUI fallback path")
    def test_linux_redirects_to_tui_when_webview_missing(self) -> None:
        """On Linux, pywebview is excluded from the wheel by a PEP 508 marker
        (see client/pyproject.toml). app.main() must spot the ImportError and
        hand off to `outwarp-cli tui` instead of crashing. Without this guard
        the entry-point would explode the first time the legacy `outwarp` shim
        was double-clicked on a default Linux install."""
        from outwarp import app as app_mod

        # Surface the same ImportError pip's marker leaves behind: no `webview`
        # in sys.modules and no import path resolving it. patch.dict ensures
        # the cleanup runs even when pywebview IS installed in the dev venv.
        with (
            patch.dict(sys.modules, {"webview": None}),
            patch("outwarp.cli.main", return_value=0) as fake_cli,
        ):
            assert app_mod.main() == 0
            fake_cli.assert_called_once_with(["tui"])

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
            def __init__(self, manager, on_show, on_quit, api=None, lang_getter=None):
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
            # Bypass the production mutex — a real OutWarp client may be
            # running on the developer's machine and holding it.
            patch.object(app_mod._SingleInstanceLock, "acquire", return_value=True),
            patch.object(app_mod._SingleInstanceLock, "release"),
        ):
            rc = app_mod.main()

        assert rc == 0
        assert captured["tray_ran"] is True
        assert captured["tray_manager"] is None
        assert captured.get("start_called") is True
        # The window was created with the OutWarp title
        kwargs = fake_webview.create_window.call_args.kwargs
        assert kwargs["title"] == "OutWarp"
        # Api was bound to the window — proves bind_window(window) was called
        assert kwargs["js_api"] is not None
        # First run with no config must show the window even if minimize_to_tray
        # is on — the user has nothing to do without the import screen.
        assert kwargs["hidden"] is False

    def test_minimize_to_tray_starts_window_hidden_when_config_exists(self, tmp_path) -> None:
        """With a profile already imported and minimize_to_tray=True, the
        webview window is created hidden so only the tray icon shows up.
        The user opens the window via the tray's "Open" entry."""
        from outwarp import app as app_mod

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(_VALID_OWCFG))
        # minimize_to_tray defaults to True, but be explicit for the test.
        (tmp_path / "settings.json").write_text(json.dumps({"minimize_to_tray": True}))

        captured = {}
        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.create_window.return_value = fake_window
        fake_webview.start.side_effect = lambda **kwargs: captured.setdefault("start_called", True)

        class _FakeTrayApp:
            def __init__(self, manager, on_show, on_quit, api=None, lang_getter=None):
                pass
            def run(self): pass
            def stop(self): pass
            def update_manager(self, m): pass

        # The TunnelManager would otherwise spin up a real worker thread the
        # moment _FakeTrayApp returns control. Patch it out — this test is
        # only about windowing.
        with (
            patch("outwarp.app.default_config_path", return_value=config_path),
            patch("outwarp.api.default_config_path", return_value=config_path),
            patch("outwarp.tunnel.TunnelManager", return_value=MagicMock()),
            patch.dict(sys.modules, {"webview": fake_webview}),
            patch("outwarp.tray.TrayApp", _FakeTrayApp),
            patch.object(app_mod._SingleInstanceLock, "acquire", return_value=True),
            patch.object(app_mod._SingleInstanceLock, "release"),
        ):
            rc = app_mod.main()

        assert rc == 0
        kwargs = fake_webview.create_window.call_args.kwargs
        assert kwargs["hidden"] is True

    def test_minimize_to_tray_off_keeps_window_visible(self, tmp_path) -> None:
        """With minimize_to_tray=False, the window is shown on launch even if
        a profile already exists."""
        from outwarp import app as app_mod

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(_VALID_OWCFG))
        (tmp_path / "settings.json").write_text(json.dumps({"minimize_to_tray": False}))

        captured = {}
        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.create_window.return_value = fake_window
        fake_webview.start.side_effect = lambda **kwargs: captured.setdefault("start_called", True)

        class _FakeTrayApp:
            def __init__(self, manager, on_show, on_quit, api=None, lang_getter=None):
                pass
            def run(self): pass
            def stop(self): pass
            def update_manager(self, m): pass

        with (
            patch("outwarp.app.default_config_path", return_value=config_path),
            patch("outwarp.api.default_config_path", return_value=config_path),
            patch("outwarp.tunnel.TunnelManager", return_value=MagicMock()),
            patch.dict(sys.modules, {"webview": fake_webview}),
            patch("outwarp.tray.TrayApp", _FakeTrayApp),
            patch.object(app_mod._SingleInstanceLock, "acquire", return_value=True),
            patch.object(app_mod._SingleInstanceLock, "release"),
        ):
            rc = app_mod.main()

        assert rc == 0
        kwargs = fake_webview.create_window.call_args.kwargs
        assert kwargs["hidden"] is False
