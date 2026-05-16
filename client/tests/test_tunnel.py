from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp.config import (
    ClientConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.network import NetworkError
from outwarp.platforms.base import Platform, PlatformError
from outwarp.tunnel import (
    Tunnel,
    TunnelError,
    build_wstunnel_command,
    find_wstunnel,
)


def _make_config() -> ClientConfig:
    return ClientConfig(
        schema_version=1,
        server=ServerConfig(endpoint="203.0.113.42", port=443, http_upgrade_path_prefix="s3cret"),
        tls=TlsConfig(cert_fingerprint_sha256="A" * 95),
        tunnel=TunnelConfig(local_port=51820, remote_host="10.0.0.1", remote_port=51820),
        wireguard=WireguardConfig(
            tunnel_name="OutWarp",
            client_address="10.0.0.42/32",
            client_private_key="priv",
            server_public_key="pub",
        ),
        routing=RoutingConfig(bypass_ips=["203.0.113.42", "203.0.113.43"]),
        reconnect=ReconnectConfig(),
    )


class FakePlatform(Platform):
    def __init__(self) -> None:
        self.installed = False
        self.routes: list[str] = []
        self.gateway = "192.168.1.1"
        self.active = True

    def install_wg_tunnel(self, name, config_text):
        self.installed = True
        return Path("/fake/path.conf")

    def uninstall_wg_tunnel(self, name):
        self.installed = False

    def is_wg_tunnel_active(self, name):
        return self.active

    def get_default_gateway(self):
        return self.gateway

    def add_host_route(self, ip, gateway):
        self.routes.append(ip)

    def remove_host_route(self, ip):
        if ip in self.routes:
            self.routes.remove(ip)

    # Autostart / kill switch aren't exercised in tunnel tests — provide cheap
    # stubs so the ABC instantiation check passes.
    def install_autostart(self, command):
        pass

    def uninstall_autostart(self):
        pass

    def is_autostart_installed(self):
        return False

    def engage_kill_switch(self, allowlist_ips):
        pass

    def release_kill_switch(self):
        pass

    def is_kill_switch_engaged(self):
        return False


# --- find_wstunnel ---

def test_find_wstunnel_uses_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "wstunnel.exe"
    fake.write_text("x")
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(fake))
    assert find_wstunnel() == fake


def test_find_wstunnel_raises_when_env_override_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(tmp_path / "nope"))
    with pytest.raises(TunnelError, match="does not exist"):
        find_wstunnel()


def test_find_wstunnel_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.delenv("OUTWARP_WSTUNNEL", raising=False)
    fake = tmp_path / "wstunnel"
    fake.write_text("x")
    with patch("outwarp.tunnel.Path") as mock_path:
        # standard location does NOT exist
        mock_path.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = False
        mock_path.side_effect = lambda x: Path(x)
        with patch("outwarp.tunnel.shutil.which", return_value=str(fake)):
            assert find_wstunnel() == fake


def test_find_wstunnel_raises_when_nowhere(monkeypatch):
    monkeypatch.delenv("OUTWARP_WSTUNNEL", raising=False)
    with patch("outwarp.tunnel.shutil.which", return_value=None):
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(TunnelError, match="wstunnel binary not found"):
                find_wstunnel()


# --- build_wstunnel_command ---

def test_build_wstunnel_command_has_expected_structure():
    cfg = _make_config()
    bin_path = Path("/usr/bin/wstunnel")
    cmd = build_wstunnel_command(cfg, bin_path)
    assert cmd[0] == str(bin_path)
    assert cmd[1] == "client"
    # wstunnel v10+ has TLS cert verification off by default and removed the
    # old --dangerous-disable-certificate-verification flag — identity is
    # checked by our own fingerprint pinning before wstunnel ever starts.
    assert "--dangerous-disable-certificate-verification" not in cmd
    assert "-L" in cmd
    forward = cmd[cmd.index("-L") + 1]
    assert forward == "udp://127.0.0.1:51820:10.0.0.1:51820?timeout_sec=0"
    assert "--http-upgrade-path-prefix" in cmd
    assert cmd[cmd.index("--http-upgrade-path-prefix") + 1] == "s3cret"
    assert cmd[-1] == "wss://203.0.113.42:443"


# --- Tunnel.connect / disconnect ---

def test_connect_happy_path():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    assert plat.installed is True
    # Bypass routing is encoded in WireGuard's AllowedIPs (see
    # wireguard._allowed_ips_excluding) rather than adding host routes on top
    # of the WG interface — the WG-NT driver on Windows captures traffic
    # before the OS routing table is consulted, so host routes don't take.
    assert plat.routes == []
    assert t._proc is fake_proc


def test_connect_reports_phases_in_order():
    """Each blocking step fires the phase callback once, in the order the UI
    stepper renders ('resolve' → 'tls' → 'wg' → 'ws')."""
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    phases: list[str] = []

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   phase_callback=phases.append)
        t.connect()

    assert phases == ["resolve", "tls", "wg", "ws"]


def test_connect_phase_stops_at_resolve_when_endpoint_unreachable():
    cfg = _make_config()
    plat = FakePlatform()
    phases: list[str] = []
    with patch("outwarp.tunnel.tcp_probe", return_value=False):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   phase_callback=phases.append)
        with pytest.raises(TunnelError, match="Cannot reach"):
            t.connect()
    assert phases == ["resolve"]


def test_connect_phase_stops_at_tls_on_fingerprint_mismatch():
    from outwarp.network import FingerprintMismatch
    cfg = _make_config()
    plat = FakePlatform()
    phases: list[str] = []
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint",
              side_effect=FingerprintMismatch("nope")),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   phase_callback=phases.append)
        with pytest.raises(TunnelError):
            t.connect()
    assert phases == ["resolve", "tls"]


def test_connect_aborts_when_endpoint_unreachable():
    cfg = _make_config()
    plat = FakePlatform()
    with patch("outwarp.tunnel.tcp_probe", return_value=False):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        with pytest.raises(TunnelError, match="Cannot reach"):
            t.connect()
    # No state should leak through
    assert plat.installed is False
    assert plat.routes == []


def test_connect_aborts_on_fingerprint_mismatch():
    cfg = _make_config()
    plat = FakePlatform()
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch(
            "outwarp.tunnel.verify_tls_fingerprint",
            side_effect=NetworkError("fingerprint mismatch boom"),
        ),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        with pytest.raises(TunnelError, match="fingerprint mismatch"):
            t.connect()
    assert plat.installed is False
    assert plat.routes == []


def test_connect_rolls_back_when_wstunnel_fails_to_launch():
    cfg = _make_config()
    plat = FakePlatform()
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", side_effect=OSError("exec failed")),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        with pytest.raises(OSError):
            t.connect()
    assert plat.installed is False
    assert plat.routes == []


def test_disconnect_reverses_state():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()
        t.disconnect()

    assert plat.installed is False
    assert plat.routes == []
    fake_proc.terminate.assert_called_once()


def test_disconnect_kills_process_if_terminate_times_out():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    import subprocess
    fake_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="wstunnel", timeout=5), None]

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()
        t.disconnect()

    fake_proc.terminate.assert_called_once()
    fake_proc.kill.assert_called_once()


def test_disconnect_tolerates_platform_errors():
    cfg = _make_config()
    plat = FakePlatform()

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    # Simulate platform errors during disconnect — disconnect must not raise
    plat.uninstall_wg_tunnel = MagicMock(side_effect=PlatformError("boom"))
    plat.remove_host_route = MagicMock(side_effect=PlatformError("boom"))
    t.disconnect()  # must complete


def test_is_active_false_when_not_started():
    cfg = _make_config()
    plat = FakePlatform()
    t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
    assert t.is_active is False


def test_is_active_false_when_proc_died():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    fake_proc.poll.return_value = 1  # process exited
    assert t.is_active is False
