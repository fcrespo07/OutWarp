from __future__ import annotations

import contextlib
import time
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
from outwarp.platforms.base import Platform, PlatformError
from outwarp.tunnel import (
    _ANSI_ESCAPE_RE,
    _WSTUNNEL_NOISE_RE,
    Tunnel,
    TunnelError,
    build_wstunnel_command,
    find_wstunnel,
)


@contextlib.contextmanager
def _apply(patches):
    """Enter a tuple of patch() context managers together."""
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


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
        std_loc = mock_path.return_value.__truediv__.return_value.__truediv__.return_value
        std_loc.exists.return_value = False
        mock_path.side_effect = lambda x: Path(x)
        with patch("outwarp.tunnel.shutil.which", return_value=str(fake)):
            assert find_wstunnel() == fake


def test_find_wstunnel_raises_when_nowhere(monkeypatch):
    monkeypatch.delenv("OUTWARP_WSTUNNEL", raising=False)
    with patch("outwarp.tunnel.shutil.which", return_value=None), \
            patch("pathlib.Path.exists", return_value=False), \
            pytest.raises(TunnelError, match="wstunnel binary not found"):
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
    # Default port 443 is omitted from the URL so the wstunnel-generated
    # Host header matches what a real browser sends — see build_wstunnel_command.
    assert cmd[-1] == "wss://203.0.113.42"


def test_build_wstunnel_command_honours_port_override():
    cfg = _make_config()
    cmd = build_wstunnel_command(cfg, Path("/usr/bin/wstunnel"), port=8443)
    assert cmd[-1] == "wss://203.0.113.42:8443"


def test_build_wstunnel_command_always_sets_ws_ping_frequency():
    # The legacy WarpSocket script kept the WS half-open detection tight at
    # 25 s so corporate NATs couldn't quietly drop the connection without
    # wstunnel noticing. We adopted the same value as a universal default.
    cmd = build_wstunnel_command(_make_config(), Path("/usr/bin/wstunnel"))
    i = cmd.index("--websocket-ping-frequency")
    assert cmd[i + 1] == "25s"


def test_build_wstunnel_command_hostile_adds_dns_bypass_flags():
    cmd = build_wstunnel_command(_make_config(), Path("/usr/bin/wstunnel"), hostile=True)
    assert "--dns-resolver" in cmd
    assert cmd[cmd.index("--dns-resolver") + 1] == "dns://1.1.1.1"
    assert "--dns-resolver-prefer-ipv4" in cmd
    # And the URL still comes at the very end.
    assert cmd[-1] == "wss://203.0.113.42"


def test_build_wstunnel_command_default_omits_dns_flags():
    cmd = build_wstunnel_command(_make_config(), Path("/usr/bin/wstunnel"))
    assert "--dns-resolver" not in cmd
    assert "--dns-resolver-prefer-ipv4" not in cmd


# --- Tunnel.connect / disconnect ---

def _handshake_after_start():
    """side_effect for get_tunnel_stats: None (baseline before wstunnel starts)
    then a fresh handshake, so a rung passes the WG-handshake verification."""
    from outwarp.wireguard import TunnelStats

    seq: list = [None]
    fresh = TunnelStats(rx_bytes=1, tx_bytes=1, latest_handshake=int(time.time()))

    def _fn(_name):
        return seq.pop(0) if seq else fresh

    return _fn


def _verified_connect_patches(popen):
    """The set of patches that make the first attempted rung succeed end-to-end:
    reachable, pin OK, wstunnel launches, WG handshakes, ping goes through."""
    return (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=popen),
        patch("outwarp.tunnel.get_tunnel_stats", side_effect=_handshake_after_start()),
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    )

def test_connect_falls_back_to_alternate_port():
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, fallback_ports=[8443]))
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    # Primary 443 is blocked; 8443 is reachable. The ladder tries every 443
    # rung (all fail the reachability pre-flight) then the alt-port rung.
    def probe(host, port, timeout=5.0):
        return port == 8443

    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return fake_proc

    with (
        patch("outwarp.tunnel.tcp_probe", side_effect=probe),
        patch("outwarp.tunnel.verify_tls_fingerprint") as vtf,
        patch("outwarp.tunnel.subprocess.Popen", side_effect=fake_popen),
        patch("outwarp.tunnel.get_tunnel_stats", side_effect=_handshake_after_start()),
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    # TLS verify and the wstunnel target both used the fallback port.
    assert vtf.call_args[0][1] == 8443
    assert captured["cmd"][-1] == "wss://203.0.113.42:8443"
    assert t.active_strategy_id == "port-8443"


def test_connect_fails_when_all_ports_unreachable():
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, fallback_ports=[8443, 2083]))
    with patch("outwarp.tunnel.tcp_probe", return_value=False):
        t = Tunnel(cfg, platform=FakePlatform(), wstunnel_bin=Path("/fake/wstunnel"))
        with pytest.raises(TunnelError, match="Cannot reach"):
            t.connect()


def test_connect_happy_path():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    with _apply(_verified_connect_patches(fake_proc)):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    assert plat.installed is True
    # Bypass routing is encoded in WireGuard's AllowedIPs (see
    # wireguard._allowed_ips_excluding) rather than adding host routes on top
    # of the WG interface — the WG-NT driver on Windows captures traffic
    # before the OS routing table is consulted, so host routes don't take.
    assert plat.routes == []
    assert t._proc is fake_proc
    # The first, cleanest rung (plain direct) wins on a friendly network.
    assert t.active_strategy_id == "direct"


def test_connect_reports_phases_in_order():
    """Each blocking step fires the phase callback once, in the order the UI
    stepper renders ('resolve' → 'tls' → 'wg' → 'ws')."""
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    phases: list[str] = []

    with _apply(_verified_connect_patches(fake_proc)):
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
    # Pre-flight reachability fails before WG is ever installed.
    assert phases == ["resolve"]
    assert plat.installed is False


def test_connect_skips_rung_on_fingerprint_mismatch_and_exhausts_ladder():
    from outwarp.network import FingerprintMismatchError
    cfg = _make_config()
    plat = FakePlatform()
    phases: list[str] = []
    # Every direct rung pins the same cert, so a persistent mismatch skips them
    # all and the ladder exhausts — but only after WG is installed (phase 'wg').
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint",
              side_effect=FingerprintMismatchError("nope")),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   phase_callback=phases.append)
        with pytest.raises(TunnelError, match="All connection strategies failed"):
            t.connect()
    assert phases == ["resolve", "tls", "wg"]
    assert plat.installed is False  # rolled back on total failure


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


def test_connect_tolerates_fingerprint_mismatch_when_allowed():
    """allow_tls_intercept lets a mismatched-pin rung proceed to verification —
    WireGuard's key auth is the real boundary on a TLS-intercepting network."""
    from outwarp.network import FingerprintMismatchError
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint",
              side_effect=FingerprintMismatchError("intercepted")),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
        patch("outwarp.tunnel.get_tunnel_stats", side_effect=_handshake_after_start()),
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   allow_tls_intercept=True)
        t.connect()
    assert t.active_strategy_id == "direct"


def test_connect_exhausts_ladder_when_wstunnel_fails_to_launch():
    cfg = _make_config()
    plat = FakePlatform()
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", side_effect=OSError("exec failed")),
        # Patching subprocess.Popen also affects the `wg show` call inside
        # get_tunnel_stats (shared module), so stub it out explicitly.
        patch("outwarp.tunnel.get_tunnel_stats", return_value=None),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        # A launch failure is a rung failure, not a hard error — the ladder
        # tries the rest, then reports a combined failure.
        with pytest.raises(TunnelError, match="All connection strategies failed"):
            t.connect()
    assert plat.installed is False
    assert plat.routes == []


def test_connect_fails_when_handshake_never_completes():
    """The core institute failure: wstunnel is up but no WG handshake (the WS
    upgrade is 400ing). The rung must be rejected, not reported as connected."""
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
        patch("outwarp.tunnel.get_tunnel_stats", return_value=None),  # never handshakes
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   handshake_timeout=0.3)
        with pytest.raises(TunnelError, match="All connection strategies failed"):
            t.connect()
    assert plat.installed is False


def test_connect_fails_when_no_traffic_through_tunnel():
    """Handshake completes but the ping through the tunnel never returns —
    datapath is dead, so the rung is rejected."""
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
        patch("outwarp.tunnel.get_tunnel_stats", side_effect=_handshake_after_start()),
        patch("outwarp.tunnel.measure_latency_ms", return_value=None),  # no reply
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   handshake_timeout=1.0)
        with pytest.raises(TunnelError, match="All connection strategies failed"):
            t.connect()
    assert plat.installed is False


def test_disconnect_reverses_state():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    with _apply(_verified_connect_patches(fake_proc)):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()
        t.disconnect()

    assert plat.installed is False
    assert plat.routes == []
    assert t.active_strategy_id == ""
    fake_proc.terminate.assert_called_once()


def test_disconnect_kills_process_if_terminate_times_out():
    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    import subprocess
    fake_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="wstunnel", timeout=5), None]

    with _apply(_verified_connect_patches(fake_proc)):
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
    with _apply(_verified_connect_patches(fake_proc)):
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

    with _apply(_verified_connect_patches(fake_proc)):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    fake_proc.poll.return_value = 1  # process exited
    assert t.is_active is False


def test_ansi_escape_re_strips_color_sequences():
    # wstunnel emits CSI/SGR colour codes around its log level / module names
    # when it thinks stdout is a TTY (which subprocess pipes look like to it).
    # The drain thread strips them before logging so the UI log panel doesn't
    # show literal `[2m...[0m` noise.
    raw = (
        "\x1b[2m2026-05-16T19:35:50.153691Z\x1b[0m \x1b[32m INFO\x1b[0m "
        "\x1b[2mwstunnel\x1b[0m: Starting"
    )
    assert _ANSI_ESCAPE_RE.sub("", raw) == "2026-05-16T19:35:50.153691Z  INFO wstunnel: Starting"


def test_ansi_escape_re_preserves_unicode_content():
    # The Rust panic message that surfaced the regression had Spanish text
    # (UTF-8 encoded). Make sure the regex doesn't eat anything beyond the
    # escape sequence itself.
    raw = (
        "\x1b[31mError\x1b[0m: Solo se permite un uso de cada "
        "dirección de socket"
    )
    assert _ANSI_ESCAPE_RE.sub("", raw) == (
        "Error: Solo se permite un uso de cada dirección de socket"
    )


def test_wstunnel_noise_re_matches_pool_rotation_lines():
    # These two are emitted ~6 times per minute by the --connection-min-idle 3
    # pool maintenance — without the filter they drown out everything else in
    # the user-facing log at INFO. _drain_stdout demotes them to DEBUG.
    tcp = (
        "2026-06-01T14:30:47.641544Z  INFO wstunnel::protocols::tcp::server: "
        "Opening TCP connection to 79.112.138.17:443"
    )
    tls = (
        "2026-06-01T14:30:47.683182Z  INFO wstunnel::protocols::tls::server: "
        "Doing TLS handshake using SNI IpAddress(V4(Ipv4Addr([79, 112, 138, 17]))) "
        "with the server 79.112.138.17:443"
    )
    assert _WSTUNNEL_NOISE_RE.search(tcp)
    assert _WSTUNNEL_NOISE_RE.search(tls)


def test_wstunnel_noise_re_keeps_interesting_lines_at_info():
    # Anything that isn't pure pool churn must NOT match — we still want
    # "Starting wstunnel client", UDP server bind announcements, errors, and
    # fingerprint mismatches surfaced at INFO.
    keep = [
        "2026-06-01T14:30:47.740924Z  INFO wstunnel: Starting wstunnel client v10.5.5",
        (
            "2026-06-01T14:30:47.740938Z  INFO wstunnel::protocols::udp::server: "
            "Starting UDP server listening cnx on 127.0.0.1:51820 with cnx timeout of 0s"
        ),
        (
            "2026-06-01T14:30:52.818649Z  INFO wstunnel::protocols::udp::server: "
            "New UDP connection from 127.0.0.1:43890"
        ),
        "ERROR wstunnel::protocols::tls::server: TLS handshake failed",
    ]
    for line in keep:
        assert not _WSTUNNEL_NOISE_RE.search(line), line
