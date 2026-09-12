from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp_server.config import ServerConfig
from outwarp_server.k8s_init import run_init

_FAKE_CERT = (
    Path("/tmp/cert.pem"),
    Path("/tmp/key.pem"),
    "AB:CD:EF",
    "spki-fingerprint",
)
_FAKE_KEYPAIR = ("wg_priv", "wg_pub")


@pytest.fixture(autouse=True)
def mock_crypto():
    """Every test that reaches key/cert generation runs against fakes.

    generate_tls_cert/generate_wg_keypair shell out to openssl and `wg
    genkey` respectively — too slow and environment-dependent for a unit
    test. Tests that expect run_init to fail before reaching them (e.g.
    missing OUTWARP_ENDPOINT) just never call these mocks.
    """
    with (
        patch("outwarp_server.k8s_init.generate_tls_cert", return_value=_FAKE_CERT) as cert,
        patch("outwarp_server.k8s_init.generate_wg_keypair", return_value=_FAKE_KEYPAIR) as keypair,
    ):
        yield cert, keypair


def test_missing_endpoint_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OUTWARP_ENDPOINT", raising=False)
    assert run_init(tmp_path) == 1
    assert not (tmp_path / "server_config.json").exists()


def test_existing_config_is_left_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_crypto
) -> None:
    config_path = tmp_path / "server_config.json"
    config_path.write_text("not valid json but never read", encoding="utf-8")
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")

    assert run_init(tmp_path) == 0

    mock_cert, mock_keypair = mock_crypto
    mock_cert.assert_not_called()
    mock_keypair.assert_not_called()
    assert config_path.read_text(encoding="utf-8") == "not valid json but never read"


def test_enroll_port_defaults_to_8444(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.delenv("OUTWARP_ENROLL_PORT", raising=False)

    assert run_init(tmp_path) == 0

    config = ServerConfig.load(tmp_path / "server_config.json")
    assert config.enroll_port == 8444


def test_enroll_port_read_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.setenv("OUTWARP_ENROLL_PORT", "9999")

    assert run_init(tmp_path) == 0

    config = ServerConfig.load(tmp_path / "server_config.json")
    assert config.enroll_port == 9999


def test_enroll_port_out_of_range_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.setenv("OUTWARP_ENROLL_PORT", "70000")

    assert run_init(tmp_path) == 1
    assert not (tmp_path / "server_config.json").exists()


def test_server_address_defaults_to_first_usable_host_of_a_slash_24(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.setenv("OUTWARP_SUBNET", "10.0.0.0/24")
    monkeypatch.delenv("OUTWARP_SERVER_ADDRESS", raising=False)

    assert run_init(tmp_path) == 0

    config = ServerConfig.load(tmp_path / "server_config.json")
    assert config.server_address == "10.0.0.1/24"


def test_server_address_defaults_to_first_usable_host_of_a_slash_16(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.setenv("OUTWARP_SUBNET", "10.8.0.0/16")
    monkeypatch.delenv("OUTWARP_SERVER_ADDRESS", raising=False)

    assert run_init(tmp_path) == 0

    config = ServerConfig.load(tmp_path / "server_config.json")
    assert config.server_address == "10.8.0.1/16"


def test_invalid_subnet_fails_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTWARP_ENDPOINT", "203.0.113.42")
    monkeypatch.setenv("OUTWARP_SUBNET", "not-a-subnet")

    assert run_init(tmp_path) == 1
    assert not (tmp_path / "server_config.json").exists()
