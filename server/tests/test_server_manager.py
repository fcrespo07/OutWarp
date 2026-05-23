from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp_server.config import ClientEntry, ServerConfig
from outwarp_server.server_manager import ServerManager, validate_client_name


def _config(clients: list[ClientEntry]) -> ServerConfig:
    return ServerConfig(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="s3cr3t",
        cert_path="/etc/outwarp/cert.pem",
        key_path="/etc/outwarp/key.pem",
        cert_fingerprint_sha256="AA:" * 31 + "AA",
        wg_private_key="server_priv",
        wg_public_key="server_pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=clients,
    )


class TestPruneExpired:
    def test_revokes_only_past_dated_clients(self, tmp_path: Path) -> None:
        clients = [
            ClientEntry("old", "k1", "10.0.0.2/32", expires_at="2000-01-01"),
            ClientEntry("live", "k2", "10.0.0.3/32", expires_at="2999-01-01"),
            ClientEntry("forever", "k3", "10.0.0.4/32"),
        ]
        mgr = ServerManager(_config(clients))
        with patch("outwarp_server.server_manager.remove_peer_live"), \
             patch("outwarp_server.server_manager.get_server_platform"), \
             patch(
                 "outwarp_server.server_manager.default_config_path",
                 return_value=tmp_path / "server_config.json",
             ):
            revoked = mgr.prune_expired(today="2026-06-01")
        assert revoked == ["old"]
        assert {c.name for c in mgr.config.clients} == {"live", "forever"}

    def test_noop_when_nothing_expired(self, tmp_path: Path) -> None:
        clients = [ClientEntry("forever", "k", "10.0.0.2/32")]
        mgr = ServerManager(_config(clients))
        with patch("outwarp_server.server_manager.default_config_path",
                   return_value=tmp_path / "server_config.json"):
            assert mgr.prune_expired(today="2026-06-01") == []
        assert len(mgr.config.clients) == 1


@pytest.mark.parametrize(
    "name",
    ["laptop", "ferra-portatil", "Casa_01", "movil.personal", "a", "Client 1", "x" * 64],
)
def test_validate_client_name_accepts_safe_names(name):
    assert validate_client_name(name) == name


def test_validate_client_name_strips_whitespace():
    assert validate_client_name("  laptop  ") == "laptop"


@pytest.mark.parametrize(
    "name",
    [
        "../secret",       # path traversal
        "..\\secret",      # windows traversal
        "a/b",             # path separator
        "a\\b",            # windows separator
        ".",               # current dir
        "..",              # parent dir
        "",                # empty
        "   ",             # whitespace only
        "x" * 65,          # too long
        "name\x00",        # null byte
        "tab\tname",       # control char
        "/abs",            # absolute-ish
        ".hidden",         # leading dot (separator-like start)
    ],
)
def test_validate_client_name_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        validate_client_name(name)


def test_validate_client_name_rejects_non_string():
    with pytest.raises(ValueError):
        validate_client_name(None)  # type: ignore[arg-type]
