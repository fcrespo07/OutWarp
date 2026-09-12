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
@patch(
    "outwarp_server.operations.generate_wg_keypair",
    return_value=("priv", "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo="),
)
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
        clients=[{
            "name": "laptop",
            "public_key": "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo=",
            "address": "10.0.0.2/32",
        }],
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
        clients=[{
            "name": "laptop",
            "public_key": "arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA=",
            "address": "10.0.0.2/32",
        }],
    )
    config = ServerConfig.load(cfg_path)
    result = operations.revoke_client(config, "laptop", config_path=cfg_path)
    assert result.name == "laptop"
    assert result.hot_removed is True
    saved = ServerConfig.load(cfg_path)
    assert saved.clients == []
    mock_remove.assert_called_once_with("arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA=")


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
    fake.manages_enroll_service = False
    mock_platform.return_value = fake
    result = operations.restart_services(config)
    assert result.wg_conf_written and result.wg_restarted and result.wstunnel_restarted
    assert result.enroll_restarted
    assert result.errors == []
    fake.install_wg_config.assert_called_once()
    fake.restart_wg.assert_called_once()
    fake.restart_wstunnel_service.assert_called_once()
    fake.restart_enroll_service.assert_called_once()
    # No OS-managed units on this platform: nothing to re-render.
    fake.install_wstunnel_service.assert_not_called()
    fake.install_enroll_service.assert_not_called()


@patch("outwarp_server.server_manager._find_wstunnel", return_value="/usr/local/bin/wstunnel")
@patch("outwarp_server.platforms.get_server_platform")
def test_restart_services_rerenders_units_where_the_os_manages_them(
    mock_platform: MagicMock, _find: MagicMock, tmp_path: Path,
) -> None:
    """`outwarp-server update` tells the admin to run `restart`: on a systemd
    install that has to rewrite both units from the current code, or a new
    argv (e.g. the enrolment `--restrict-to`) and a unit that did not exist
    before the upgrade (outwarp-enroll.service) never reach systemd."""
    cfg_path = _write_server_config(tmp_path)
    config = ServerConfig.load(cfg_path)
    fake = MagicMock()
    fake.manages_enroll_service = True
    mock_platform.return_value = fake

    result = operations.restart_services(config, config_path=cfg_path)

    assert result.errors == []
    wstunnel_exec = fake.install_wstunnel_service.call_args.args[0]
    assert f"--restrict-to 127.0.0.1:{config.enroll_port}" in wstunnel_exec
    enroll_exec = fake.install_enroll_service.call_args.args[0]
    assert enroll_exec.endswith(f"--config-dir {tmp_path} enroll-listener")
    fake.restart_wstunnel_service.assert_called_once()
    fake.restart_enroll_service.assert_called_once()


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.remove_peer_live")
@patch(
    "outwarp_server.operations.generate_psk",
    return_value="rY2vuEB4VDipfXtL8xlnizgU9eBsI2tQfKw7L4xLFIw=",
)
@patch(
    "outwarp_server.operations.generate_wg_keypair",
    return_value=("new_priv", "eY7+WjKbAd6NrjDOJb7LaSSd8WQHl0BszTY9yzKoGyA="),
)
def test_rotate_client_replaces_keypair_and_rewrites_owcfg(
    _kg: MagicMock, _psk: MagicMock, mock_remove: MagicMock,
    mock_add: MagicMock, tmp_path: Path,
) -> None:
    old_pub = "yYzBcQWtwdHBN0USGevIH8L0z9WaUDItBX1ZLZMkYpk="
    new_pub = "eY7+WjKbAd6NrjDOJb7LaSSd8WQHl0BszTY9yzKoGyA="
    cfg_path = _write_server_config(
        tmp_path,
        clients=[{"name": "laptop", "public_key": old_pub, "address": "10.0.0.2/32"}],
    )
    config = ServerConfig.load(cfg_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = operations.rotate_client(config, "laptop", config_path=cfg_path, output_dir=out_dir)

    assert result.client.public_key == new_pub
    assert result.client.address == "10.0.0.2/32"  # preserved
    assert result.owcfg_path == out_dir / "laptop.owcfg"
    assert result.owcfg_path.exists()

    saved = ServerConfig.load(cfg_path)
    assert saved.clients[0].public_key == new_pub

    mock_remove.assert_called_once_with(old_pub)
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


# --- key-pin backfill for servers set up before spki_sha256 existed ---

@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_backfills_the_key_pin_from_the_certificate(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    from outwarp_server.crypto import generate_tls_cert

    cert_path, key_path, fp, spki = generate_tls_cert("vpn.example.com", tmp_path / "tls")
    cfg_path = _write_server_config(
        tmp_path, cert_path=str(cert_path), key_path=str(key_path),
        cert_fingerprint_sha256=fp,  # note: no spki_sha256, as an old server has
    )
    config = ServerConfig.load(cfg_path)
    assert config.spki_sha256 == ""

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = operations.add_client(
        config, "laptop", config_path=cfg_path, output_dir=out_dir,
    )

    owcfg = json.loads(result.owcfg_path.read_text(encoding="utf-8"))
    assert owcfg["tls"]["spki_sha256"] == spki
    assert owcfg["schema_version"] == 2


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub"))
def test_add_client_still_works_when_the_certificate_is_unreadable(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    # Best-effort backfill: a server whose cert lives somewhere this process
    # can't read must still be able to issue a (v1) profile.
    cfg_path = _write_server_config(tmp_path)  # cert_path points at nothing
    config = ServerConfig.load(cfg_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = operations.add_client(
        config, "laptop", config_path=cfg_path, output_dir=out_dir,
    )

    owcfg = json.loads(result.owcfg_path.read_text(encoding="utf-8"))
    assert owcfg["schema_version"] == 1
    assert "spki_sha256" not in owcfg["tls"]


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch(
    "outwarp_server.operations.generate_wg_keypair",
    return_value=(
        "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
        "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo=",
    ),
)
def test_add_client_produces_a_signed_owcfg_the_real_client_accepts(
    _kg: MagicMock, _psk: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    """CONCEPTO-C prop.2 end-to-end: add_client lazily generates this server's
    signing key, embeds a signature in the .owcfg it writes, and a real
    client (not a mock of one) accepts and pins it on import."""
    try:
        from outwarp.config import import_owcfg
    except ImportError:
        pytest.skip("Client package not installed in this environment")

    cfg_path = _write_server_config(
        tmp_path,
        # A valid-shaped WG key: the client validates server_public_key
        # (FIX-01), so the fixture's usual placeholder "srv_pub" would fail
        # for a reason unrelated to what this test is checking.
        wg_public_key="RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
    )
    config = ServerConfig.load(cfg_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = operations.add_client(
        config, "laptop", config_path=cfg_path, output_dir=out_dir,
    )

    owcfg = json.loads(result.owcfg_path.read_text(encoding="utf-8"))
    assert "signing" in owcfg
    # The signing key was persisted, not just used in memory.
    assert ServerConfig.load(cfg_path).owcfg_signing_private_key

    known_servers = tmp_path / "known_servers.json"
    with patch("outwarp.profile_trust.known_servers_path", return_value=known_servers):
        client_cfg = import_owcfg(result.owcfg_path, dest=tmp_path / "config.json", enroll=False)

    assert client_cfg.server.endpoint == "203.0.113.42"
    pinned = json.loads(known_servers.read_text(encoding="utf-8"))
    assert pinned["203.0.113.42"] == owcfg["signing"]["public_key"]


@patch("outwarp_server.operations.add_peer_live")
@patch("outwarp_server.operations.remove_peer_live")
@patch("outwarp_server.operations.generate_psk", return_value="")
@patch(
    "outwarp_server.operations.generate_wg_keypair",
    return_value=("priv2", "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo="),
)
def test_add_client_reuses_a_revoked_name(
    _kg: MagicMock, _psk: MagicMock, _rm: MagicMock, _add: MagicMock, tmp_path: Path,
) -> None:
    """Regression (0.12.0 soft-delete): revoking 'laptop' must not burn the
    name forever — re-issuing the same device name is the normal flow."""
    from outwarp_server.client_store import ClientStore

    cfg_path = _write_server_config(
        tmp_path,
        clients=[{
            "name": "laptop",
            "public_key": "arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA=",
            "address": "10.0.0.2/32",
        }],
    )
    config = ServerConfig.load(cfg_path)
    operations.revoke_client(config, "laptop", config_path=cfg_path)

    config = ServerConfig.load(cfg_path)
    result = operations.add_client(config, "laptop", config_path=cfg_path, output_dir=tmp_path)

    assert result.client.name == "laptop"
    rows = ClientStore(tmp_path / "clients.sqlite").list_all()
    assert [r.state for r in rows] == ["active"]
    assert rows[0].public_key == "vn4n9d0JyfC8GQOt0YuK61s+3+kDkxCZ3a087Q5WSAo="
    # An active duplicate is still refused.
    config = ServerConfig.load(cfg_path)
    with pytest.raises(ValueError, match="already exists"):
        operations.add_client(config, "laptop", config_path=cfg_path, output_dir=tmp_path)
