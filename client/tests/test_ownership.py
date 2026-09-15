"""One tunnel owner at a time across GUI, TUI, `connect` and the daemon."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp import ownership

_VALID_OWCFG = {
    "schema_version": 1,
    "server": {"endpoint": "203.0.113.42", "port": 443, "http_upgrade_path_prefix": "x"},
    "tls": {"cert_fingerprint_sha256":
            ("AB:CD:EF:01:23:45:67:89:" * 3) + "AB:CD:EF:01:23:45:67:89"},
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "OutWarp", "client_address": "10.0.0.42/32",
        "client_private_key": "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
        "server_public_key": "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
}


def _names() -> dict[str, str]:
    tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    return {"mutex_name": f"Local\\OutWarpOwn-{tag}", "lock_file": f"outwarp-own-{tag}.lock"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock semantics")
class TestTunnelOwnerLock:
    def test_second_holder_loses_and_sees_the_pid(self) -> None:
        names = _names()
        a, b = ownership.TunnelOwnerLock(**names), ownership.TunnelOwnerLock(**names)
        assert a.acquire() is True
        assert b.acquire() is False
        assert ownership.owner_pid(names["lock_file"]) == os.getpid()
        a.release()
        assert b.acquire() is True
        b.release()

    def test_describe_owner_prefers_the_service(self, monkeypatch) -> None:
        monkeypatch.setattr(ownership, "service_is_active", lambda: True)
        assert "outwarp-client.service" in ownership.describe_owner()
        monkeypatch.setattr(ownership, "service_is_active", lambda: False)
        monkeypatch.setattr(ownership, "owner_pid", lambda lock_file=ownership.LOCK_NAME: 4242)
        assert "4242" in ownership.describe_owner()


def _write_profile() -> None:
    from outwarp.config import default_config_path

    p = default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_VALID_OWCFG))


@pytest.mark.skipif(sys.platform == "win32", reason="daemon path is Linux-first")
def test_daemon_refuses_when_another_process_owns_the_tunnel(monkeypatch) -> None:
    from outwarp import service

    _write_profile()
    holder = ownership.TunnelOwnerLock()
    assert holder.acquire()
    try:
        with patch("outwarp.service.TunnelManager") as tm:
            rc = service.run_daemon()
    finally:
        holder.release()
    assert rc == service.EXIT_TUNNEL_OWNED == 4
    tm.assert_not_called()


def test_unit_never_restarts_on_no_profile_or_owned_elsewhere() -> None:
    from outwarp import service

    body = service._unit_content(Path("/usr/local/bin/outwarp"))
    assert "RestartPreventExitStatus=2 4" in body


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX")
def test_connect_honours_settings_and_the_lock(monkeypatch, capsys) -> None:
    from outwarp import cli
    from outwarp.settings import load_settings, save_settings

    _write_profile()
    s = load_settings()
    s.update({"kill_switch": True, "allow_tls_intercept": True, "auto_reconnect": False})
    save_settings(s)

    seen: dict = {}

    class _FakeManager:
        def __init__(self, config, **kw):
            seen.update(kw)
            self.state = None
            self.last_error = None
        def add_listener(self, cb): pass
        def start(self): pass
        def stop(self): pass

    monkeypatch.setattr(cli, "TunnelManager", _FakeManager)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)
    with patch("outwarp.killswitch.release_stale_async") as rel, \
         patch("threading.Event.wait", return_value=True):
        assert cli.main(["connect"]) == 0
    assert seen == {
        "allow_tls_intercept": True, "auto_reconnect": False, "kill_switch_enabled": True,
    }
    rel.assert_not_called()  # kill switch on → engaged rule is protection

    holder = ownership.TunnelOwnerLock()
    assert holder.acquire()
    try:
        assert cli.main(["connect"]) == 1
    finally:
        holder.release()
    assert "already run by" in capsys.readouterr().err


def test_expired_profile_fails_fast_in_the_manager_and_at_import(tmp_path: Path) -> None:
    from outwarp.config import ConfigError, _parse, import_owcfg_text
    from outwarp.tunnel import TunnelManager, TunnelState

    raw = dict(_VALID_OWCFG, meta={"expires_at": "2000-01-01"})
    config = _parse(raw)
    assert config.is_expired()
    with (
        patch("outwarp.tunnel.get_platform"),
        patch("outwarp.tunnel.shutil.which", return_value="/x/wstunnel"),
    ):
        mgr = TunnelManager(config)
        states: list[TunnelState] = []
        mgr.add_listener(states.append)
        mgr._run()
    assert states[-1] is TunnelState.FAILED
    assert "expired on 2000-01-01" in (mgr.last_error or "")

    with pytest.raises(ConfigError, match="expired on 2000-01-01"):
        import_owcfg_text(json.dumps(raw), dest=tmp_path / "config.json")


@pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
def test_install_service_refuses_without_a_profile(monkeypatch) -> None:
    from outwarp import service

    monkeypatch.setattr(service, "service_supported", lambda: (True, ""))
    out: list[str] = []
    assert service.install_service(echo=out.append) == 2
    assert "No profile imported" in out[-1]


@pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
def test_install_service_reports_the_real_systemctl_error(monkeypatch) -> None:
    from outwarp import service

    _write_profile()
    monkeypatch.setattr(service, "service_supported", lambda: (True, ""))
    monkeypatch.setattr(
        service, "_resolve_daemon_executable", lambda: Path("/usr/local/bin/outwarp"),
    )

    def fake_systemctl(*args):
        r = MagicMock()
        r.returncode = 1
        r.stderr = "Failed to connect to user scope bus via local transport: No medium found\n"
        r.stdout = ""
        return r

    monkeypatch.setattr(service, "_systemctl", fake_systemctl)
    out: list[str] = []
    assert service.install_service(echo=out.append) == 1
    assert "No medium found" in out[-1]


@pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
def test_service_supported_rejects_root(monkeypatch) -> None:
    from outwarp import service

    monkeypatch.setattr(service.shutil, "which", lambda n: "/usr/bin/systemctl")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    ok, why = service.service_supported()
    assert ok is False and "root" in why


def test_resolve_daemon_executable_prefers_the_running_venv(tmp_path: Path, monkeypatch) -> None:
    from outwarp import service

    exe = tmp_path / "bin" / "outwarp"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "bin" / "python"))
    monkeypatch.setattr(service.shutil, "which", lambda n: "/usr/local/bin/outwarp-cli")
    assert service._resolve_daemon_executable() == exe.resolve()


def test_set_linger_never_prompts(monkeypatch) -> None:
    from outwarp import service

    calls: list[dict] = []

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, **kw})
        r = MagicMock()
        r.returncode = 0
        return r

    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.shutil, "which", lambda n: "/usr/bin/loginctl")
    monkeypatch.setattr(service, "_current_user", lambda: "alice")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    assert service.set_linger(True) == (True, "")
    assert calls[0]["cmd"] == ["loginctl", "--no-ask-password", "enable-linger", "alice"]
    assert calls[0]["stdin"] is service.subprocess.DEVNULL


class TestApiServiceHandover:
    def _api(self, monkeypatch):
        from outwarp.api import Api

        mgr = MagicMock()
        mgr.config = MagicMock()
        mgr.is_active = True
        api = Api(MagicMock(), mgr)
        return api, mgr

    @pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
    def test_enable_stops_own_manager_then_installs_and_becomes_viewer(self, monkeypatch) -> None:
        api, mgr = self._api(monkeypatch)
        order: list[str] = []
        mgr.stop.side_effect = lambda: order.append("stop")
        def fake_install(echo):
            order.append("install")
            echo("Service enabled.")
            return 0

        with patch("outwarp.service.install_service", side_effect=fake_install):
            res = api.set_service_enabled(True)
        assert res["ok"] is True
        assert order == ["stop", "install"]
        assert api.connect()["ok"] is False
        assert api._status_str() == "connected"  # viewer reads the interface

    @pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
    def test_enable_failure_restarts_own_manager(self, monkeypatch) -> None:
        api, mgr = self._api(monkeypatch)
        def fake_install(echo):
            echo("boom: no medium found")
            return 1

        with patch("outwarp.service.install_service", side_effect=fake_install):
            res = api.set_service_enabled(True)
        assert res["ok"] is False and "no medium found" in res["error"]
        mgr.start.assert_called_once()
        assert api._service_managed is False

    @pytest.mark.skipif(sys.platform != "linux", reason="systemd path")
    def test_start_at_boot_refused_while_service_managed(self, monkeypatch) -> None:
        api, mgr = self._api(monkeypatch)
        api._service_managed = True
        res = api.set_settings({"start_at_boot": True})
        assert res["ok"] is False and "service" in res["error"].lower()

    def test_set_settings_rereads_disk_before_merging(self, monkeypatch) -> None:
        from outwarp.settings import load_settings, save_settings

        api, mgr = self._api(monkeypatch)
        s = load_settings()
        s["preferred_ui"] = "tui"  # changed by the TUI/CLI
        save_settings(s)
        api.set_settings({"advanced": True})
        after = load_settings()
        assert after["advanced"] is True and after["preferred_ui"] == "tui"
