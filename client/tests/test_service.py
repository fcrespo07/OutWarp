"""Tests for outwarp.service — daemon runtime + systemd-user install.

The daemon runtime (run_daemon) shares the TunnelManager with cli.connect,
so we don't re-test the tunnel state machine here; we cover only the
service-management plumbing that test_cli.py historically skipped.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp import service


@pytest.fixture
def fake_unit_dir(tmp_path, monkeypatch):
    """Pin _user_unit_dir() to a tmpdir so install/uninstall don't touch the
    developer's real ~/.config/systemd/user."""
    target = tmp_path / "systemd" / "user"
    monkeypatch.setattr(service, "_user_unit_dir", lambda: target)
    return target


# ── _unit_content ──────────────────────────────────────────────────────────


def test_unit_content_contains_required_directives():
    """The generated unit must reference the exact executable + 'daemon' verb;
    a regression here would silently break service install on every distro."""
    content = service._unit_content(Path("/opt/pipx/venvs/outwarp-client/bin/outwarp-cli"))
    assert "ExecStart=/opt/pipx/venvs/outwarp-client/bin/outwarp-cli daemon" in content
    assert "Restart=on-failure" in content
    assert "WantedBy=default.target" in content
    assert "Type=simple" in content


# ── install_service ────────────────────────────────────────────────────────


def test_install_service_writes_unit_and_runs_systemctl(fake_unit_dir, monkeypatch, capsys):
    """install_service should:
       1) create the unit dir if missing
       2) write outwarp-client.service with ExecStart pointing at outwarp-cli
       3) call `systemctl --user daemon-reload`
       4) call `systemctl --user enable --now outwarp-client.service`
    """
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        service, "_resolve_daemon_executable", lambda: Path("/usr/local/bin/outwarp-cli"),
    )

    calls = []

    def fake_systemctl(*args):
        calls.append(args)
        return MagicMock(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(service, "_systemctl", fake_systemctl)

    rc = service.install_service()
    assert rc == 0

    unit_path = fake_unit_dir / "outwarp-client.service"
    assert unit_path.exists()
    body = unit_path.read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/outwarp-cli daemon" in body

    assert calls == [("daemon-reload",), ("enable", "--now", "outwarp-client.service")]


def test_install_service_refuses_on_non_linux(monkeypatch, capsys):
    monkeypatch.setattr(service.sys, "platform", "win32")
    rc = service.install_service()
    assert rc == 2
    assert "Linux" in capsys.readouterr().err


def test_install_service_refuses_without_systemctl(monkeypatch, capsys):
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda _: None)
    rc = service.install_service()
    assert rc == 2
    assert "systemctl" in capsys.readouterr().err


def test_install_service_propagates_systemctl_failure(fake_unit_dir, monkeypatch, capsys):
    """A non-zero systemctl exit (eg. user not lingering, unit syntax error)
    must surface as a non-zero CLI exit so the installer/CI can react."""
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        service, "_resolve_daemon_executable", lambda: Path("/usr/local/bin/outwarp-cli"),
    )
    monkeypatch.setattr(
        service, "_systemctl",
        lambda *args: MagicMock(returncode=5, stderr="enable failed", stdout=""),
    )
    rc = service.install_service()
    assert rc != 0
    assert "enable failed" in capsys.readouterr().err


# ── uninstall_service ──────────────────────────────────────────────────────


def test_uninstall_service_removes_unit_and_disables(fake_unit_dir, monkeypatch, capsys):
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: f"/usr/bin/{name}")

    fake_unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = fake_unit_dir / "outwarp-client.service"
    unit_path.write_text("dummy", encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        service, "_systemctl",
        lambda *args: (calls.append(args) or MagicMock(returncode=0, stderr="", stdout="")),
    )

    rc = service.uninstall_service()
    assert rc == 0
    assert not unit_path.exists()
    assert ("disable", "--now", "outwarp-client.service") in calls
    assert ("daemon-reload",) in calls


def test_uninstall_service_tolerates_missing_unit(fake_unit_dir, monkeypatch, capsys):
    """Re-running uninstall after a partial install should succeed quietly,
    not bomb on the missing unit file."""
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        service, "_systemctl",
        lambda *args: MagicMock(returncode=0, stderr="", stdout=""),
    )
    rc = service.uninstall_service()
    assert rc == 0
    assert "No unit file" in capsys.readouterr().out


# ── CLI dispatch ───────────────────────────────────────────────────────────


def test_cli_daemon_dispatch_forwards_to_run_daemon():
    """`outwarp-cli daemon --allow-tls-intercept` must hand the flag through
    to outwarp.service.run_daemon — otherwise the systemd unit can't opt
    into the TLS-intercept escape hatch."""
    from outwarp import cli
    with patch("outwarp.service.run_daemon", return_value=0) as mock_run:
        rc = cli.main(["daemon", "--allow-tls-intercept"])
    assert rc == 0
    mock_run.assert_called_once_with(allow_tls_intercept=True)


def test_cli_service_dispatch_install():
    from outwarp import cli
    with patch("outwarp.service.install_service", return_value=0) as mock_install:
        rc = cli.main(["service", "install"])
    assert rc == 0
    mock_install.assert_called_once_with()


def test_cli_service_dispatch_uninstall():
    from outwarp import cli
    with patch("outwarp.service.uninstall_service", return_value=0) as mock_un:
        rc = cli.main(["service", "uninstall"])
    assert rc == 0
    mock_un.assert_called_once_with()


def test_cli_service_dispatch_status():
    from outwarp import cli
    with patch("outwarp.service.service_status", return_value=0) as mock_st:
        rc = cli.main(["service", "status"])
    assert rc == 0
    mock_st.assert_called_once_with()
