from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server import operations
from outwarp_server.config import ServerConfig


def _write_server_config(tmp_path: Path, **overrides: object) -> Path:
    defaults = {
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
        "clients": [],
    }
    defaults.update(overrides)
    path = tmp_path / "server_config.json"
    path.write_text(json.dumps(defaults), encoding="utf-8")
    return path


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_writes_owcfg_and_updates_config(
    _kg: MagicMock, _psk: MagicMock, mock_add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = operations.add_client(
        config, "laptop", config_path=cfg_path, output_dir=out_dir,
    )

    assert result.client.name == "laptop"
    assert result.client.address == "10.0.0.2/32"
    assert result.owcfg_path == out_dir / "laptop.owcfg"
    assert result.owcfg_path.exists()
    assert result.owcfg_sha256.count(":") == 31  # 32 bytes as XX:XX:... pairs

    saved = ServerConfig.load(cfg_path)
    assert [c.name for c in saved.clients] == ["laptop"]
    mock_add.assert_called_once()


@patch("outwarp_server.operations.add_peer_live", side_effect=RuntimeError("wg not up"))
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_marks_hot_added_false_when_wg_down(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    result = operations.add_client(
        config, "laptop", config_path=cfg_path, output_dir=tmp_path,
    )
    assert result.hot_added is False
    # The .owcfg is still produced — the user can use it later when WG is up.
    assert result.owcfg_path.exists()


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_rejects_duplicate(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(
        tmp_path,
        clients=[{"name": "laptop", "public_key": "k", "address": "10.0.0.2/32"}],
    )
    config = ServerConfig.load(cfg_path)
    with pytest.raises(ValueError, match="already exists"):
        operations.add_client(
            config, "laptop", config_path=cfg_path, output_dir=tmp_path,
        )


@patch("outwarp_server.operations.remove_peer_live")
def test_revoke_client_removes_from_config(
    mock_remove: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(
        tmp_path,
        clients=[{"name": "laptop", "public_key": "k1", "address": "10.0.0.2/32"}],
    )
    config = ServerConfig.load(cfg_path)
    result = operations.revoke_client(config, "laptop", config_path=cfg_path)
    assert result.name == "laptop"
    assert result.hot_removed is True
    saved = ServerConfig.load(cfg_path)
    assert saved.clients == []
    mock_remove.assert_called_once_with("k1")


def test_revoke_unknown_raises(tmp_path: Path) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    with pytest.raises(KeyError, match="not found"):
        operations.revoke_client(config, "ghost", config_path=cfg_path)


@patch("outwarp_server.platforms.get_server_platform")
def test_restart_services_returns_all_three_true_on_success(
    mock_platform: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    fake = MagicMock()
    mock_platform.return_value = fake
    result = operations.restart_services(config)
    assert result.wg_conf_written and result.wg_restarted and result.wstunnel_restarted
    assert result.errors == []
    fake.install_wg_config.assert_called_once()
    fake.restart_wg.assert_called_once()
    fake.restart_wstunnel_service.assert_called_once()


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.remove_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="newpsk")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("new_priv", "new_pub"))
def test_rotate_client_replaces_keypair_and_rewrites_owcfg(
    _kg: MagicMock, _psk: MagicMock, mock_remove: MagicMock,
    mock_add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(
        tmp_path,
        clients=[{"name": "laptop", "public_key": "old_pub", "address": "10.0.0.2/32"}],
    )
    config = ServerConfig.load(cfg_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = operations.rotate_client(config, "laptop", config_path=cfg_path, output_dir=out_dir)

    assert result.client.public_key == "new_pub"
    assert result.client.address == "10.0.0.2/32"  # preserved
    assert result.owcfg_path == out_dir / "laptop.owcfg"
    assert result.owcfg_path.exists()

    saved = ServerConfig.load(cfg_path)
    assert saved.clients[0].public_key == "new_pub"

    mock_remove.assert_called_once_with("old_pub")
    mock_add.assert_called_once()


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.remove_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("p", "q"))
def test_rotate_client_raises_for_unknown(
    _kg: MagicMock, _psk: MagicMock, _rm: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    with pytest.raises(ValueError, match="not found"):
        operations.rotate_client(config, "ghost", config_path=cfg_path)


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_rejects_path_traversal_name(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    with pytest.raises(ValueError):
        operations.add_client(config, "../evil", config_path=cfg_path, output_dir=tmp_path)


@patch("outwarp_server.platforms.get_server_platform")
def test_restart_services_stops_after_wg_restart_failure(
    mock_platform: MagicMock, tmp_path: Path,
) -> None:
    from outwarp_server.platforms.base import PlatformError

    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    fake = MagicMock()
    fake.restart_wg.side_effect = PlatformError("boom")
    mock_platform.return_value = fake

    result = operations.restart_services(config)
    assert result.wg_conf_written is True
    assert result.wg_restarted is False
    assert result.wstunnel_restarted is False
    assert any("boom" in e for e in result.errors)
    fake.restart_wstunnel_service.assert_not_called()
