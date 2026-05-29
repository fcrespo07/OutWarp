from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from outwarp.tui.app import OutWarpClientTUI
from outwarp.tui.modals.import_owcfg import ImportModal
from outwarp.tui.screens.empty import EmptyScreen
from outwarp.tui.screens.failed import FailedScreen


def _write_owcfg(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "name": "laptop",
        "server": {"endpoint": "vpn.example.com", "port": 443,
                   "http_upgrade_path_prefix": "s3cr3t"},
        "tls": {"cert_fingerprint_sha256": "AB:" * 31 + "AB"},
        "tunnel": {"local_port": 51820, "remote_host": "10.13.13.1",
                   "remote_port": 51820},
        "wireguard": {
            "tunnel_name": "OutWarp", "client_address": "10.13.13.5/32",
            "client_private_key": "priv", "server_public_key": "pub",
            "dns": ["1.1.1.1"], "mtu": 1380,
        },
        "routing": {"bypass_ips": ["203.0.113.42"]},
        "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
    }
    path = tmp_path / "laptop.owcfg"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_empty_state_when_no_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, EmptyScreen)
        await pilot.press("i")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ImportModal)


@pytest.mark.asyncio
async def test_failed_screen_when_wstunnel_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    # Point OUTWARP_WSTUNNEL at a path that does not exist so find_wstunnel
    # raises TunnelError → TUI routes to FailedScreen.
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(tmp_path / "nope"))
    # Import a valid .owcfg first so config exists.
    from outwarp.config import import_owcfg
    import_owcfg(_write_owcfg(tmp_path))

    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, FailedScreen), type(app.screen).__name__
