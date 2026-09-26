from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from outwarp_server import service_install
from outwarp_server.config import ServerConfig
from outwarp_server.platforms.base import PlatformError


def _config() -> ServerConfig:
    return ServerConfig(
        schema_version=1, endpoint="203.0.113.42", port=443,
        http_upgrade_path_prefix="secret",
        cert_path="/etc/outwarp/tls/cert.pem", key_path="/etc/outwarp/tls/key.pem",
        cert_fingerprint_sha256="AB:CD", wg_private_key="priv", wg_public_key="pub",
        subnet="10.0.0.0/24", server_address="10.0.0.1/24", wg_listen_port=51820,
        clients=[],
    )


def _install(platform: MagicMock, tmp_path: Path) -> tuple[bool, list[tuple]]:
    steps: list[tuple] = []
    with (
        patch.object(service_install, "get_server_platform", return_value=platform),
        patch.object(service_install, "enable_ip_forwarding"),
        patch.object(service_install, "configure_ufw_if_active", return_value=False),
    ):
        ok = service_install.install_services(
            _config(), tmp_path / "server_config.json", Path("/usr/local/bin/wstunnel"),
            lambda *step: steps.append(step),
        )
    return ok, steps


def test_installs_wireguard_then_both_units(tmp_path: Path) -> None:
    platform = MagicMock()
    platform.is_wg_active.return_value = False
    ok, steps = _install(platform, tmp_path)

    assert ok is True
    assert [s[0] for s in steps] == ["forwarding", "wireguard", "wstunnel", "enroll"]
    assert platform.reconcile.call_args.kwargs["force_restart"] is False
    assert "--restrict-to 127.0.0.1:51820" in platform.install_wstunnel_service.call_args.args[0]
    assert platform.install_enroll_service.call_args.args[0].endswith(
        f"--config-dir {tmp_path} enroll-listener"
    )


def test_forces_a_restart_when_rerun_on_a_live_interface(tmp_path: Path) -> None:
    platform = MagicMock()
    platform.is_wg_active.return_value = True
    _install(platform, tmp_path)
    assert platform.reconcile.call_args.kwargs["force_restart"] is True


def test_stops_at_the_first_failure(tmp_path: Path) -> None:
    platform = MagicMock()
    platform.is_wg_active.return_value = False
    platform.install_wstunnel_service.side_effect = PlatformError("denied")
    ok, steps = _install(platform, tmp_path)

    assert ok is False
    assert steps[-1] == ("wstunnel", False, "denied")
    platform.install_enroll_service.assert_not_called()
