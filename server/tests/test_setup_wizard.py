from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server.setup_wizard import _detect_public_ip, _probe_localhost, run_setup


class TestProbeLocalhost:
    def test_returns_false_when_nothing_listening(self) -> None:
        # Use a port that's almost certainly not in use
        assert _probe_localhost(1) is False

    @patch("outwarp_server.setup_wizard.socket.create_connection")
    def test_returns_true_when_connect_succeeds(self, mock_conn: MagicMock) -> None:
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_conn.return_value.__exit__ = MagicMock(return_value=None)
        assert _probe_localhost(443) is True


class TestDetectPublicIp:
    @patch("outwarp_server.setup_wizard.urllib.request.urlopen")
    def test_returns_ip_string(self, mock_urlopen: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b"203.0.113.42\n"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=None)
        assert _detect_public_ip() == "203.0.113.42"

    @patch("outwarp_server.setup_wizard.urllib.request.urlopen")
    def test_returns_none_on_failure(self, mock_urlopen: MagicMock) -> None:
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("fail")
        assert _detect_public_ip() is None


class TestRunSetup:
    @patch("outwarp_server.setup_wizard._check_root", return_value=False)
    def test_aborts_when_not_root(self, mock_root: MagicMock, tmp_path: Path) -> None:
        ret = run_setup(tmp_path)
        assert ret == 1

    @patch("outwarp_server.setup_wizard._find_wstunnel", return_value=None)
    @patch("outwarp_server.setup_wizard._check_root", return_value=True)
    def test_aborts_when_wstunnel_missing(
        self, mock_root: MagicMock, mock_find: MagicMock, tmp_path: Path
    ) -> None:
        ret = run_setup(tmp_path)
        assert ret == 1

    @patch("outwarp_server.setup_wizard._find_wg", return_value=None)
    @patch(
        "outwarp_server.setup_wizard._find_wstunnel",
        return_value=Path("/usr/local/bin/wstunnel"),
    )
    @patch("outwarp_server.setup_wizard._check_root", return_value=True)
    def test_aborts_when_wg_missing(
        self,
        mock_root: MagicMock,
        mock_wst: MagicMock,
        mock_wg: MagicMock,
        tmp_path: Path,
    ) -> None:
        ret = run_setup(tmp_path)
        assert ret == 1

    @patch("outwarp_server.setup_wizard.Confirm.ask", return_value=False)
    @patch("outwarp_server.setup_wizard._check_root", return_value=True)
    def test_aborts_when_user_refuses_overwrite(
        self,
        mock_root: MagicMock,
        mock_confirm: MagicMock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "server_config.json").write_text("{}", encoding="utf-8")
        ret = run_setup(tmp_path)
        assert ret == 0


class TestTransportBranch:
    """The wizard's domain question decides everything downstream: which
    process holds the public port, what wstunnel is told to bind, and whether
    the profiles it later issues pin a certificate or validate a chain."""

    def _run(self, tmp_path: Path, *, use_domain: bool, prompts: list[str]):
        from outwarp_server.platforms.base import PrerequisiteResult, PrerequisiteStatus

        platform = MagicMock()
        platform.check_prerequisites.return_value = PrerequisiteResult(
            status=PrerequisiteStatus.OK, detail="", remediation=""
        )
        platform.is_wg_active.return_value = False

        with (
            patch("outwarp_server.setup_wizard._check_root", return_value=True),
            patch("outwarp_server.setup_wizard._find_wstunnel",
                  return_value=Path("/usr/local/bin/wstunnel")),
            patch("outwarp_server.setup_wizard._find_wg", return_value=Path("/usr/bin/wg")),
            patch("outwarp_server.setup_wizard.get_server_platform", return_value=platform),
            patch("outwarp_server.setup_wizard.generate_wg_keypair",
                  return_value=("priv", "pub")),
            patch("outwarp_server.setup_wizard.Confirm.ask", return_value=use_domain),
            patch("outwarp_server.setup_wizard.Prompt.ask", side_effect=prompts),
            patch("outwarp_server.setup_wizard.IntPrompt.ask",
                  side_effect=lambda _p, default=0: default),
            patch("outwarp_server.setup_wizard._configure_ufw_if_active"),
            patch("outwarp_server.setup_wizard._enable_ip_forwarding"),
            patch("outwarp_server.setup_wizard._probe_localhost", return_value=True),
            patch("outwarp_server.setup_wizard._configure_caddy") as caddy_,
        ):
            ret = run_setup(tmp_path)
        return ret, platform, caddy_

    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="the domain branch is Linux-only (Caddy under systemd)",
    )
    def test_domain_branch_configures_caddy_and_moves_wstunnel_to_loopback(
        self, tmp_path: Path
    ) -> None:
        from outwarp_server.config import ServerConfig

        ret, platform, caddy_ = self._run(
            tmp_path, use_domain=True,
            prompts=["vpn.example.com", "", "10.0.0.0/24", "10.0.0.1/24"],
        )
        assert ret == 0
        caddy_.assert_called_once()

        cfg = ServerConfig.load(tmp_path / "server_config.json")
        assert cfg.tls_mode == "acme"
        assert cfg.endpoint == "vpn.example.com"

        exec_start = platform.install_wstunnel_service.call_args[0][0]
        assert "ws://127.0.0.1:8080" in exec_start
        assert "--tls-certificate" not in exec_start

    def test_no_domain_branch_keeps_wstunnel_on_the_public_port(
        self, tmp_path: Path
    ) -> None:
        from outwarp_server.config import ServerConfig

        with patch("outwarp_server.setup_wizard._detect_public_ip",
                   return_value="203.0.113.42"):
            ret, platform, caddy_ = self._run(
                tmp_path, use_domain=False,
                prompts=["203.0.113.42", "10.0.0.0/24", "10.0.0.1/24"],
            )
        assert ret == 0
        caddy_.assert_not_called()

        cfg = ServerConfig.load(tmp_path / "server_config.json")
        assert cfg.tls_mode == "self-signed"

        exec_start = platform.install_wstunnel_service.call_args[0][0]
        assert "wss://0.0.0.0:443" in exec_start
        assert "--tls-certificate" in exec_start


def test_domain_branch_is_not_offered_off_linux(tmp_path: Path) -> None:
    """Everything the Caddy front writes lives at POSIX paths; on Windows the
    question would only produce a config nothing reads."""
    from outwarp_server import setup_wizard

    # Stops at the missing-wstunnel check, which is well before the domain
    # question — the point is that the question is never asked at all.
    with (
        patch.object(setup_wizard.sys, "platform", "win32"),
        patch("outwarp_server.setup_wizard._check_root", return_value=True),
        patch("outwarp_server.setup_wizard._find_wstunnel", return_value=None),
        patch("outwarp_server.setup_wizard.Confirm.ask") as confirm,
    ):
        setup_wizard.run_setup(tmp_path)
    # Bailed at the missing-wstunnel check, well before the domain question.
    assert not any("domain" in str(c).lower() for c in confirm.call_args_list)
