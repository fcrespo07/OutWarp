"""Disabling a client is reversible: the peer leaves the interface but the row
keeps its name, IP, keys, PSK and expiry, so enabling it needs no new .owcfg."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server import operations
from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.wireguard import build_server_wg_conf, build_server_wg_conf_windows

PUB = "arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA="
PSK = "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo="


def _config_path(tmp_path: Path, **client: object) -> Path:
    entry = {"name": "laptop", "public_key": PUB, "psk": PSK, "address": "10.0.0.2/32",
             "expires_at": "2099-01-01"}
    entry.update(client)
    path = tmp_path / "server_config.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "endpoint": "203.0.113.42",
        "port": 443,
        "http_upgrade_path_prefix": "s3cr3t",
        "cert_path": str(tmp_path / "cert.pem"),
        "key_path": str(tmp_path / "key.pem"),
        "cert_fingerprint_sha256": "AB:" * 31 + "AB",
        "wg_private_key": "srv_priv",
        "wg_public_key": "srv_pub",
        "subnet": "10.0.0.0/24",
        "server_address": "10.0.0.1/24",
        "wg_listen_port": 51820,
        "clients": [entry],
    }), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_os_wg_config():
    with patch("outwarp_server.platforms.get_server_platform") as gp:
        yield gp.return_value


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.remove_peer_live")
def test_disable_then_enable_round_trips_the_same_peer(
    mock_remove: MagicMock, mock_add: MagicMock, tmp_path: Path, _no_os_wg_config: MagicMock,
) -> None:
    cfg_path = _config_path(tmp_path)
    before = ServerConfig.load(cfg_path).clients[0]

    off = operations.set_client_enabled(
        ServerConfig.load(cfg_path), "laptop", False, config_path=cfg_path,
    )
    assert off.hot_applied is True
    mock_remove.assert_called_once_with(PUB)
    disabled = ServerConfig.load(cfg_path).clients[0]
    assert disabled.state == "disabled"
    # Still registered, with everything needed to come back unchanged.
    assert (disabled.address, disabled.public_key, disabled.psk, disabled.expires_at) == (
        before.address, before.public_key, before.psk, before.expires_at,
    )
    written = _no_os_wg_config.install_wg_config.call_args.args[0]
    assert PUB not in written

    operations.set_client_enabled(
        ServerConfig.load(cfg_path), "laptop", True, config_path=cfg_path,
    )
    mock_add.assert_called_once_with(PUB, "10.0.0.2/32", psk=PSK)
    assert ServerConfig.load(cfg_path).clients[0] == before
    assert PUB in _no_os_wg_config.install_wg_config.call_args.args[0]


@patch("outwarp_server.operations.remove_peer_live", side_effect=RuntimeError("wg down"))
def test_disable_persists_even_when_wireguard_is_down(
    _remove: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _config_path(tmp_path)
    result = operations.set_client_enabled(
        ServerConfig.load(cfg_path), "laptop", False, config_path=cfg_path,
    )
    assert result.hot_applied is False
    assert ServerConfig.load(cfg_path).clients[0].state == "disabled"


@patch("outwarp_server.operations.add_peer_live")
def test_enabling_an_expired_client_does_not_put_it_back_on_the_interface(
    mock_add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _config_path(tmp_path, state="disabled", expires_at="2000-01-01")
    operations.set_client_enabled(
        ServerConfig.load(cfg_path), "laptop", True, config_path=cfg_path,
    )
    mock_add.assert_not_called()


@patch("outwarp_server.operations.generate_psk", return_value=PSK)
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("new_priv", PSK))
@patch("outwarp_server.operations.remove_peer_live")
@patch("outwarp_server.operations.add_peer_live")
def test_disabled_stays_off_when_rotated_or_enrolled(
    mock_add: MagicMock, mock_remove: MagicMock, _kg: MagicMock, _psk: MagicMock,
    tmp_path: Path,
) -> None:
    cfg_path = _config_path(tmp_path, state="disabled")
    operations.rotate_client(
        ServerConfig.load(cfg_path), "laptop", config_path=cfg_path, output_dir=tmp_path,
    )
    mock_add.assert_not_called()
    mock_remove.assert_not_called()
    assert ServerConfig.load(cfg_path).clients[0].state == "disabled"

    (tmp_path / "p").mkdir()
    pending_path = _config_path(tmp_path / "p", public_key="", state="disabled")
    result = operations.complete_enrollment(
        ServerConfig.load(pending_path), "laptop", PUB, config_path=pending_path,
    )
    assert result.hot_added is False
    mock_add.assert_not_called()
    enrolled = ServerConfig.load(pending_path).clients[0]
    assert (enrolled.public_key, enrolled.state) == (PUB, "disabled")


@pytest.mark.parametrize("enabled", [True, False])
def test_unknown_or_revoked_client_is_refused(tmp_path: Path, enabled: bool) -> None:
    cfg_path = _config_path(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        operations.set_client_enabled(
            ServerConfig.load(cfg_path), "ghost", enabled, config_path=cfg_path,
        )
    with patch("outwarp_server.operations.remove_peer_live"):
        operations.revoke_client(ServerConfig.load(cfg_path), "laptop", config_path=cfg_path)
    with pytest.raises(KeyError, match="not found"):
        operations.set_client_enabled(
            ServerConfig.load(cfg_path), "laptop", enabled, config_path=cfg_path,
        )


@pytest.mark.parametrize("build", [build_server_wg_conf, build_server_wg_conf_windows])
def test_wg_conf_builders_skip_disabled_peers(tmp_path: Path, build) -> None:
    config = ServerConfig.load(_config_path(tmp_path))
    on = ClientEntry(name="on", public_key=PUB, address="10.0.0.2/32")
    off = ClientEntry(name="off", public_key=PSK, address="10.0.0.3/32", state="disabled")
    from dataclasses import replace
    conf = build(replace(config, clients=[on, off]))
    assert PUB in conf
    assert PSK not in conf
    assert "# off" not in conf


def test_config_accepts_the_disabled_state(tmp_path: Path) -> None:
    assert ServerConfig.load(_config_path(tmp_path, state="disabled")).clients[0].state \
        == "disabled"


def test_cli_disable_and_enable(tmp_path: Path, capsys) -> None:
    from outwarp_server import cli

    cfg_path = _config_path(tmp_path)
    args = argparse.Namespace(name="laptop", config_dir=str(tmp_path))
    with patch.object(cli, "_resolve_config_path", return_value=cfg_path), \
            patch.object(cli, "_load_config", side_effect=lambda _a: ServerConfig.load(cfg_path)), \
            patch("outwarp_server.operations.remove_peer_live"), \
            patch("outwarp_server.operations.add_peer_live"):
        assert cli._cmd_disable_client(args) == 0
        assert ServerConfig.load(cfg_path).clients[0].state == "disabled"
        assert "enable-client laptop" in " ".join(capsys.readouterr().out.split())
        assert cli._cmd_enable_client(args) == 0
        assert ServerConfig.load(cfg_path).clients[0].state == "active"
        args.name = "ghost"
        assert cli._cmd_disable_client(args) == 1


def test_api_reports_disabled_and_toggles(tmp_path: Path) -> None:
    from outwarp_server.api import Api

    manager = MagicMock()
    manager.config.clients = [
        ClientEntry(name="laptop", public_key=PUB, address="10.0.0.2/32", state="disabled"),
    ]
    api = Api.__new__(Api)
    api._manager = manager
    api._emit = MagicMock()
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        rows = api.list_clients()
        assert rows[0]["status"] == "disabled"
        assert rows[0]["enrolled"] is True
        assert api.set_client_enabled("laptop", True) == {"ok": True}
    manager.set_client_enabled.assert_called_once_with("laptop", True)

    manager.set_client_enabled.side_effect = ValueError("Client 'x' not found")
    with patch("outwarp_server.api.get_live_peers", return_value={}):
        assert api.set_client_enabled("x", False)["ok"] is False


def test_panel_allows_the_toggle() -> None:
    from outwarp_server.web_server import ALLOWED_METHODS

    assert "set_client_enabled" in ALLOWED_METHODS
