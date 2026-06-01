"""Tests for the outwarp-cli entry point.

These exercise the argument parser plus the import/status/profile/uninstall
flows. `connect` and `logs --follow` are intentionally NOT covered here —
both block on signals and would deadlock pytest without a fairly heavy
threading/timeout harness. They're driven by the same TunnelManager that
test_tunnel_manager.py already covers.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp import cli
from outwarp.config import default_config_path


VALID_OWCFG = {
    "schema_version": 1,
    "name": "ci-test",
    "server": {
        "endpoint": "203.0.113.42",
        "port": 443,
        "http_upgrade_path_prefix": "s3cr3t",
    },
    "tls": {
        "cert_fingerprint_sha256": "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:"
                                    "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89",
    },
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "OutWarp",
        "client_address": "10.0.0.42/32",
        "client_private_key": "dGVzdGtleQ==",
        "server_public_key": "c2VydmVya2V5",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
    "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
}


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect default_config_path() to a tmp dir so tests never touch the
    real user config. Also patches the path resolver inside outwarp.cli."""
    fake_cfg = tmp_path / "outwarp" / "config.json"
    fake_cfg.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("outwarp.cli.default_config_path", lambda: fake_cfg)
    monkeypatch.setattr("outwarp.config.default_config_path", lambda: fake_cfg)
    return fake_cfg


@pytest.fixture
def imported_profile(isolated_config):
    isolated_config.write_text(json.dumps(VALID_OWCFG), encoding="utf-8")
    # The "original" snapshot is written by import_owcfg; mirror it manually.
    isolated_config.with_name("config.original.json").write_text(
        json.dumps(VALID_OWCFG), encoding="utf-8"
    )
    return isolated_config


# ── argparse plumbing ───────────────────────────────────────────────────────


def test_parser_help_no_command(capsys):
    """No subcommand → argparse exits with code 2 and prints usage."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


def test_parser_unknown_command(capsys):
    with pytest.raises(SystemExit):
        cli.main(["nope"])


def test_parser_version(capsys):
    """--version should print and exit 0."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0


# ── import ──────────────────────────────────────────────────────────────────


def test_import_success(tmp_path, isolated_config, capsys):
    owcfg = tmp_path / "profile.owcfg"
    owcfg.write_text(json.dumps(VALID_OWCFG), encoding="utf-8")

    rc = cli.main(["import", str(owcfg)])
    assert rc == 0
    assert isolated_config.exists()
    out = capsys.readouterr().out
    assert "Imported profile" in out
    assert "203.0.113.42:443" in out


def test_import_missing_file(tmp_path, isolated_config, capsys):
    rc = cli.main(["import", str(tmp_path / "nope.owcfg")])
    assert rc == 1
    assert "file not found" in capsys.readouterr().err


def test_import_invalid_json(tmp_path, isolated_config, capsys):
    bad = tmp_path / "bad.owcfg"
    bad.write_text("{not json", encoding="utf-8")
    rc = cli.main(["import", str(bad)])
    assert rc == 1
    assert "invalid .owcfg" in capsys.readouterr().err


# ── status ──────────────────────────────────────────────────────────────────


def test_status_no_profile(isolated_config, capsys):
    rc = cli.main(["status"])
    assert rc == 0
    assert "No profile imported" in capsys.readouterr().out


def test_status_active(imported_profile, capsys):
    fake_platform = MagicMock()
    fake_platform.is_wg_tunnel_active.return_value = True
    with patch("outwarp.cli.get_platform", return_value=fake_platform):
        rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WG status:   active" in out
    assert "ci-test" in out


def test_status_inactive(imported_profile, capsys):
    fake_platform = MagicMock()
    fake_platform.is_wg_tunnel_active.return_value = False
    with patch("outwarp.cli.get_platform", return_value=fake_platform):
        rc = cli.main(["status"])
    assert rc == 0
    assert "WG status:   inactive" in capsys.readouterr().out


def test_status_platform_error(imported_profile, capsys):
    from outwarp.platforms import PlatformError

    fake_platform = MagicMock()
    fake_platform.is_wg_tunnel_active.side_effect = PlatformError("helper missing")
    with patch("outwarp.cli.get_platform", return_value=fake_platform):
        rc = cli.main(["status"])
    assert rc == 0
    assert "unknown" in capsys.readouterr().out


# ── profile ─────────────────────────────────────────────────────────────────


def test_profile_show(imported_profile, capsys):
    rc = cli.main(["profile"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "203.0.113.42:443" in out
    assert "10.0.0.42/32" in out
    assert "OutWarp" in out


def test_profile_without_config(isolated_config, capsys):
    rc = cli.main(["profile"])
    assert rc == 1
    assert "Run 'outwarp-cli import" in capsys.readouterr().err


# ── logs ────────────────────────────────────────────────────────────────────


def test_logs_no_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("outwarp.cli.default_log_path", lambda: tmp_path / "missing.log")
    rc = cli.main(["logs"])
    assert rc == 0
    assert "No log file yet" in capsys.readouterr().out


def test_logs_print(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "outwarp.log"
    log_path.write_text("line1\nline2\n", encoding="utf-8")
    monkeypatch.setattr("outwarp.cli.default_log_path", lambda: log_path)
    rc = cli.main(["logs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "line1" in out and "line2" in out


# ── forget-profile (was: `uninstall` in 0.4.x) ──────────────────────────────


def test_forget_profile_no_profile(isolated_config, capsys):
    rc = cli.main(["forget-profile", "--yes"])
    assert rc == 0
    assert "Nothing to remove" in capsys.readouterr().out


def test_forget_profile_removes_profile(imported_profile):
    fake_platform = MagicMock()
    fake_platform.is_wg_tunnel_active.return_value = False
    with patch("outwarp.cli.get_platform", return_value=fake_platform):
        rc = cli.main(["forget-profile", "--yes"])
    assert rc == 0
    assert not imported_profile.exists()
    assert not imported_profile.with_name("config.original.json").exists()


def test_forget_profile_refuses_while_active(imported_profile, capsys):
    fake_platform = MagicMock()
    fake_platform.is_wg_tunnel_active.return_value = True
    with patch("outwarp.cli.get_platform", return_value=fake_platform):
        rc = cli.main(["forget-profile", "--yes"])
    assert rc == 1
    assert imported_profile.exists()
    assert "Refusing to remove" in capsys.readouterr().err


# ── uninstall (delegates to outwarp.uninstall.main) ─────────────────────────


def test_uninstall_subcommand_delegates_to_uninstall_main(isolated_config):
    """The new ``outwarp-cli uninstall`` is the system-wide purge that 0.4.x
    shipped as a separate ``outwarp-uninstall`` binary. Verify the dispatch
    forwards to ``outwarp.uninstall.main`` and propagates --yes."""
    with patch("outwarp.uninstall.main", return_value=0) as mock_main:
        rc = cli.main(["uninstall", "--yes"])
    assert rc == 0
    mock_main.assert_called_once_with(["--yes"])


def test_uninstall_subcommand_without_yes_forwards_none(isolated_config):
    """Without --yes the dispatch forwards ``None`` so the underlying parser
    falls back to its own interactive confirmation."""
    with patch("outwarp.uninstall.main", return_value=0) as mock_main:
        rc = cli.main(["uninstall"])
    assert rc == 0
    mock_main.assert_called_once_with(None)


# ── gui (delegates to outwarp.app.main) ─────────────────────────────────────


def test_gui_subcommand_delegates_to_app_main(isolated_config):
    """``outwarp-cli gui`` replaces the standalone ``outwarp`` gui-script.
    The dispatch table forwards to ``outwarp.app.main`` so the boot logic
    only lives in one place."""
    with patch("outwarp.app.main", return_value=0) as mock_main:
        rc = cli.main(["gui"])
    assert rc == 0
    mock_main.assert_called_once_with()
