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
from outwarp.tunnel import TunnelState


@pytest.fixture
def fake_unit_dir(tmp_path, monkeypatch):
    """Pin _user_unit_dir() to a tmpdir so install/uninstall don't touch the
    developer's real ~/.config/systemd/user."""
    target = tmp_path / "systemd" / "user"
    monkeypatch.setattr(service, "_user_unit_dir", lambda: target)
    return target


# ── run_daemon ─────────────────────────────────────────────────────────────


def test_run_daemon_returns_2_without_profile(monkeypatch):
    """No imported .owcfg → the service must exit non-zero (not hang) so
    systemd's Restart=on-failure surfaces the misconfiguration in the journal."""
    monkeypatch.setattr(service, "setup_logging", lambda: None)
    monkeypatch.setattr(service, "release_stale_async", lambda: None)

    def _raise(_path):
        raise service.ConfigError("no profile")

    monkeypatch.setattr(service.ClientConfig, "load", _raise)
    assert service.run_daemon() == 2


def _daemon_env(monkeypatch, *, kill_switch=False):
    """Stub everything around run_daemon except the manager's listener hook,
    which tests drive by hand to model tunnel state changes."""
    import threading

    monkeypatch.setattr(service, "setup_logging", lambda: None)
    released = []
    monkeypatch.setattr(service, "release_stale_async", lambda: released.append(True))
    fake_cfg = MagicMock()
    fake_cfg.server.endpoint = "203.0.113.10"
    fake_cfg.server.port = 443
    monkeypatch.setattr(service.ClientConfig, "load", lambda _p: fake_cfg)
    monkeypatch.setattr(service, "load_settings", lambda: {"kill_switch": kill_switch})
    monkeypatch.setattr(service.signal, "signal", lambda *a, **k: None)
    notified = []
    monkeypatch.setattr(service, "_notify", lambda *a, **k: notified.append((a, k)))

    mgr = MagicMock()
    mgr.last_error = "no WireGuard handshake"
    captured_kwargs = {}

    def _fake_manager(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return mgr

    monkeypatch.setattr(service, "TunnelManager", _fake_manager)
    return mgr, captured_kwargs, released, notified, threading.Event()


def test_run_daemon_starts_then_stops_on_signal(monkeypatch):
    """Happy path: build + start the manager, and on SIGTERM (modelled by an
    already-set stop event) stop it cleanly and return 0."""
    mgr, _kw, _rel, _n, stop = _daemon_env(monkeypatch)
    stop.set()
    rc = service.run_daemon(stop=stop)
    assert rc == 0
    mgr.start.assert_called_once()
    mgr.stop.assert_called_once()


def test_run_daemon_exits_nonzero_when_the_schedule_is_exhausted(monkeypatch):
    """The daemon used to sit idle in FAILED forever, so Restart=on-failure
    never fired: a laptop that booted before Wi-Fi had no tunnel until the
    unit was restarted by hand. Giving up must be an exit the service
    manager can see — and, having never connected, not a notification."""
    mgr, _kw, _rel, notified, stop = _daemon_env(monkeypatch)

    def _start():
        listener = mgr.add_listener.call_args.args[0]
        listener(TunnelState.CONNECTING)
        listener(TunnelState.FAILED)

    mgr.start.side_effect = _start
    rc = service.run_daemon(stop=stop)
    assert rc == service.EXIT_GAVE_UP == 3
    mgr.stop.assert_called_once()
    assert notified == []


def test_run_daemon_notifies_a_drop_but_not_a_boot_time_miss(monkeypatch):
    mgr, _kw, _rel, notified, stop = _daemon_env(monkeypatch)

    def _start():
        listener = mgr.add_listener.call_args.args[0]
        listener(TunnelState.CONNECTING)
        listener(TunnelState.CONNECTED)
        listener(TunnelState.RECONNECTING)
        listener(TunnelState.FAILED)

    mgr.start.side_effect = _start
    assert service.run_daemon(stop=stop) == service.EXIT_GAVE_UP
    messages = [a[1] for a, _k in notified]
    assert messages == [
        "Connected",
        "Connection dropped — reconnecting...",
        "Connection failed: no WireGuard handshake",
    ]


def test_run_daemon_releases_stale_kill_switch_only_when_the_switch_is_off(monkeypatch):
    """CONCEPTO-E / FIX-06b: the daemon is the systemd ExecStart= target — the
    primary Linux path per CLAUDE.md — and used to never touch the kill switch
    at all. A crash-orphaned rule is cleared at startup when the user has the
    switch off. With it on, the rule is what the user asked for: after a
    FAILED exit the service manager restarts us, and releasing here would
    open the network for the minutes the next attempt takes."""
    _mgr, kw, released, _n, stop = _daemon_env(monkeypatch, kill_switch=False)
    stop.set()
    assert service.run_daemon(stop=stop) == 0
    assert released == [True]
    assert kw["kill_switch_enabled"] is False

    _mgr, kw, released, _n, stop = _daemon_env(monkeypatch, kill_switch=True)
    stop.set()
    assert service.run_daemon(stop=stop) == 0
    assert released == []
    assert kw["kill_switch_enabled"] is True


# ── _unit_content ──────────────────────────────────────────────────────────


def test_unit_content_contains_required_directives():
    """The generated unit must reference the exact executable + 'daemon' verb;
    a regression here would silently break service install on every distro."""
    content = service._unit_content(Path("/opt/pipx/venvs/outwarp-client/bin/outwarp"))
    assert "ExecStart=/opt/pipx/venvs/outwarp-client/bin/outwarp daemon" in content
    assert "Restart=on-failure" in content
    assert "WantedBy=default.target" in content
    assert "Type=simple" in content


# ── install_service ────────────────────────────────────────────────────────


def test_install_service_writes_unit_and_runs_systemctl(fake_unit_dir, monkeypatch, capsys):
    """install_service should:
       1) create the unit dir if missing
       2) write outwarp-client.service with ExecStart pointing at outwarp
       3) call `systemctl --user daemon-reload`
       4) call `systemctl --user enable --now outwarp-client.service`
    """
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        service, "_resolve_daemon_executable", lambda: Path("/usr/local/bin/outwarp"),
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
    assert "ExecStart=/usr/local/bin/outwarp daemon" in body

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
        service, "_resolve_daemon_executable", lambda: Path("/usr/local/bin/outwarp"),
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
    """`outwarp daemon --allow-tls-intercept` must hand the flag through
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


class TestUnitUsesLegacyName:
    def test_detects_old_execstart(self, tmp_path: Path) -> None:
        unit = tmp_path / "outwarp-client.service"
        unit.write_text(service._unit_content(Path("/opt/pipx/venvs/outwarp-client/bin/outwarp-cli")))
        assert service.unit_uses_legacy_name(unit) is True

    def test_new_name_is_clean(self, tmp_path: Path) -> None:
        unit = tmp_path / "outwarp-client.service"
        unit.write_text(service._unit_content(Path("/usr/local/bin/outwarp")))
        assert service.unit_uses_legacy_name(unit) is False

    def test_missing_unit_is_not_legacy(self, tmp_path: Path) -> None:
        assert service.unit_uses_legacy_name(tmp_path / "nope.service") is False

    def test_resolves_new_name_before_alias(self, monkeypatch) -> None:
        order: list[str] = []

        def fake_which(name: str) -> str | None:
            order.append(name)
            return "/usr/local/bin/outwarp-cli" if name == "outwarp-cli" else None

        monkeypatch.setattr(service.shutil, "which", fake_which)
        assert service._resolve_daemon_executable() == Path("/usr/local/bin/outwarp-cli").resolve()
        assert order == ["outwarp", "outwarp-cli"]
