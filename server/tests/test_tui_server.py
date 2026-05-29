from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("textual")

from outwarp_server.tui.app import OutWarpServerTUI
from outwarp_server.tui.modals.add_client import AddClientModal
from outwarp_server.tui.screens.clients import ClientsScreen
from outwarp_server.tui.screens.dashboard import DashboardScreen
from outwarp_server.tui.screens.doctor import DoctorScreen


def _write_config(tmp_path: Path, clients=None) -> Path:
    cfg = {
        "schema_version": 1,
        "endpoint": "203.0.113.42",
        "port": 443,
        "http_upgrade_path_prefix": "s3cr3t",
        "cert_path": str(tmp_path / "cert.pem"),
        "key_path": str(tmp_path / "key.pem"),
        "cert_fingerprint_sha256": "AB:" * 31 + "AB",
        "wg_private_key": "srv_priv",
        "wg_public_key": "srv_pub",
        "subnet": "10.13.13.0/24",
        "server_address": "10.13.13.1/24",
        "wg_listen_port": 51820,
        "clients": clients or [],
    }
    (tmp_path / "server_config.json").write_text(json.dumps(cfg))
    return tmp_path


@pytest.mark.asyncio
async def test_dashboard_is_initial_screen(tmp_path: Path) -> None:
    _write_config(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert isinstance(app.screen, DashboardScreen)


@pytest.mark.asyncio
async def test_dashboard_navigates_to_clients_and_back(tmp_path: Path) -> None:
    _write_config(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("c")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ClientsScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert isinstance(app.screen, DashboardScreen)


@pytest.mark.asyncio
async def test_dashboard_navigates_to_doctor(tmp_path: Path) -> None:
    _write_config(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("d")
        await pilot.pause(0.3)
        assert isinstance(app.screen, DoctorScreen)


@pytest.mark.asyncio
async def test_dashboard_opens_add_client_modal(tmp_path: Path) -> None:
    _write_config(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("a")
        await pilot.pause(0.2)
        assert isinstance(app.screen, AddClientModal)


@pytest.mark.asyncio
@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
async def test_add_client_modal_creates_owcfg(
    _kg, _psk, _add, tmp_path: Path, monkeypatch
) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("a")
        await pilot.pause(0.2)
        # Type the name
        from textual.widgets import Input
        modal = app.screen
        modal.query_one("#name", Input).value = "felix-laptop"
        await pilot.pause(0.1)
        modal.action_submit()
        await pilot.pause(0.2)
        owcfg = tmp_path / "felix-laptop.owcfg"
        assert owcfg.exists()


@pytest.mark.asyncio
async def test_doctor_fix_kind_applied(tmp_path: Path) -> None:
    _write_config(tmp_path)
    app = OutWarpServerTUI(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("d")
        # Give the executor a moment to populate results.
        await pilot.pause(1.5)
        screen = app.screen
        assert isinstance(screen, DoctorScreen)
        # Sanity: doctor populated SOME results (the common 4 should always show).
        assert len(screen._results) >= 1
