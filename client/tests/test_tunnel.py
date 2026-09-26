from __future__ import annotations

import contextlib
import time
from dataclasses import replace
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
from outwarp.fallback import build_ladder
from outwarp.platforms.base import Platform, PlatformError
from outwarp.tunnel import (
    _ANSI_ESCAPE_RE,
    _WSTUNNEL_NOISE_RE,
    TransportUnavailableError,
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


def test_connect_fails_before_wireguard_when_wstunnel_is_gone(tmp_path, monkeypatch):
    # Defender quarantined wstunnel.exe after the Tunnel resolved it: fail with
    # the cause before WireGuard captures all traffic for a dead transport.
    binary = tmp_path / "wstunnel"
    binary.write_text("x")
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(binary))
    plat = FakePlatform()
    t = Tunnel(_make_config(), platform=plat)
    assert t._ensure_wstunnel() == binary
    binary.unlink()

    with pytest.raises(TransportUnavailableError, match="was removed"):
        t.connect()
    assert plat.installed is False


def test_tunnel_builds_without_wstunnel(tmp_path, monkeypatch):
    # The GUI constructs its TunnelManager at startup; a quarantined binary
    # must not crash it before the integrity banner can explain.
    monkeypatch.setenv("OUTWARP_WSTUNNEL", str(tmp_path / "missing"))
    t = Tunnel(_make_config(), platform=FakePlatform())
    with pytest.raises(TransportUnavailableError):
        t.connect()


def test_blocked_wstunnel_aborts_the_ladder():
    # Smart App Control / WDAC: the file is there but may not run. Every rung
    # would fail the same way, so the ladder stops at the first one.
    cfg = _make_config()
    plat = FakePlatform()
    blocked = OSError("An Application Control policy has blocked this file")
    blocked.winerror = 4551
    popen = MagicMock(side_effect=blocked)

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", popen),
        patch("outwarp.tunnel.get_tunnel_stats", return_value=None),
        pytest.raises(TransportUnavailableError, match="could not be run"),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    assert popen.call_count == 1
    assert plat.installed is False


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


# --- _check_pin: which trust check runs for which rung ---

def _strategy(**kw):
    from outwarp.fallback import ConnectionStrategy
    base = dict(
        id="direct", label="Direct", endpoint="203.0.113.42", port=443,
        path_prefix="s3cret",
    )
    return ConnectionStrategy(**{**base, **kw})


class TestCheckPin:
    def _tunnel(self, cfg, **kw):
        return Tunnel(cfg, platform=MagicMock(), wstunnel_bin=Path("/fake/wstunnel"), **kw)

    def test_ca_rung_validates_the_chain_not_the_fingerprint(self):
        cfg = replace(_make_config(), tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"))
        t = self._tunnel(cfg)
        with (
            patch("outwarp.tunnel.verify_tls_ca") as ca,
            patch("outwarp.tunnel.verify_tls_fingerprint") as fp,
        ):
            ok, reason = t._check_pin(_strategy(pin_mode="ca"))
        assert (ok, reason) == (True, "")
        ca.assert_called_once()
        fp.assert_not_called()

    def test_ca_rung_fails_closed_on_untrusted_chain(self):
        from outwarp.network import CertificateNotTrustedError

        t = self._tunnel(_make_config())
        with patch("outwarp.tunnel.verify_tls_ca",
                   side_effect=CertificateNotTrustedError("self-signed")):
            ok, reason = t._check_pin(_strategy(pin_mode="ca"))
        assert ok is False
        assert "not trusted" in reason

    def test_allow_tls_intercept_does_not_soften_ca_mode(self):
        """wstunnel enforces --tls-verify-certificate itself on a CA rung, so
        waving the check through here would only trade a clear error for a
        silent timeout a minute later."""
        from outwarp.network import CertificateNotTrustedError

        t = self._tunnel(_make_config(), allow_tls_intercept=True)
        with patch("outwarp.tunnel.verify_tls_ca",
                   side_effect=CertificateNotTrustedError("intercepted")):
            ok, _ = t._check_pin(_strategy(pin_mode="ca"))
        assert ok is False

    def test_pin_rung_prefers_the_key_pin_when_the_profile_has_one(self):
        cfg = replace(
            _make_config(),
            tls=TlsConfig(cert_fingerprint_sha256="A" * 95, spki_sha256="B" * 95),
        )
        t = self._tunnel(cfg)
        with (
            patch("outwarp.tunnel.verify_tls_spki") as spki,
            patch("outwarp.tunnel.verify_tls_fingerprint") as fp,
        ):
            ok, _ = t._check_pin(_strategy())
        assert ok is True
        spki.assert_called_once_with("203.0.113.42", 443, "B" * 95, connect_host=None)
        fp.assert_not_called()

    def test_pin_rung_falls_back_to_the_cert_pin_for_v1_profiles(self):
        t = self._tunnel(_make_config())
        with (
            patch("outwarp.tunnel.verify_tls_spki") as spki,
            patch("outwarp.tunnel.verify_tls_fingerprint") as fp,
        ):
            ok, _ = t._check_pin(_strategy())
        assert ok is True
        fp.assert_called_once_with("203.0.113.42", 443, "A" * 95, connect_host=None)
        spki.assert_not_called()

    def test_key_pin_mismatch_is_still_tolerable_when_the_user_opted_in(self):
        from outwarp.network import FingerprintMismatchError

        cfg = replace(
            _make_config(),
            tls=TlsConfig(cert_fingerprint_sha256="A" * 95, spki_sha256="B" * 95),
        )
        t = self._tunnel(cfg, allow_tls_intercept=True)
        with patch("outwarp.tunnel.verify_tls_spki",
                   side_effect=FingerprintMismatchError("mismatch")):
            ok, _ = t._check_pin(_strategy())
        assert ok is True


def test_cancel_mid_ladder_stops_before_next_rung_and_tears_down():
    """Regression: TunnelManager.stop() during a running ladder used to tear
    WG down while the ladder went on to spawn the next rung's wstunnel — an
    orphan that later died with 'failed printing to stderr: Broken pipe'.
    A cancel during rung 1 must abort without launching rung 2 and must leave
    the interface uninstalled and the current process terminated."""
    from threading import Timer

    cfg = _make_config()
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    popen = MagicMock(return_value=fake_proc)
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", popen),
        patch("outwarp.tunnel.get_tunnel_stats", return_value=None),  # never handshakes
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    ):
        # Long handshake wait: without cancellation the ladder would sit here
        # for seconds per rung; the cancel must cut rung 1 short.
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"),
                   handshake_timeout=10.0)
        Timer(0.2, t.cancel).start()
        start = time.monotonic()
        with pytest.raises(TunnelError, match="cancelled"):
            t.connect()
        assert time.monotonic() - start < 3.0

    assert popen.call_count == 1, "a second rung was launched after cancellation"
    fake_proc.terminate.assert_called()
    assert plat.installed is False


def test_cancel_before_spawn_never_launches_wstunnel():
    """A cancel that lands before the first spawn (e.g. during the pin check)
    must not start any wstunnel at all."""
    cfg = _make_config()
    plat = FakePlatform()
    popen = MagicMock()
    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.verify_tls_fingerprint"),
        patch("outwarp.tunnel.subprocess.Popen", popen),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.cancel()
        with pytest.raises(TunnelError, match="cancelled"):
            t.connect()
    popen.assert_not_called()
    assert plat.installed is False


def test_direct_endpoints_are_resolved_before_wireguard_comes_up():
    """Regression: once WG is up its DNS is routed into the (still dead)
    tunnel, so a hostname lookup in the pin check stalled ~49 s per rung. The
    endpoint must be resolved before install_wg_tunnel and the pin check must
    connect to that address, keeping the hostname only as SNI."""
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, endpoint="vpn.example.org"),
                  routing=replace(cfg.routing, bypass_ips=["vpn.example.org"]))
    plat = FakePlatform()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    events: list[str] = []
    real_install = plat.install_wg_tunnel

    def install(name, conf):
        events.append("wg-up")
        return real_install(name, conf)

    plat.install_wg_tunnel = install  # type: ignore[method-assign]

    def getaddrinfo(host, *a, **k):
        events.append(f"resolve:{host}")
        return [(2, 1, 6, "", ("203.0.113.42", 0))]

    with (
        patch("outwarp.tunnel.tcp_probe", return_value=True),
        patch("outwarp.tunnel.socket.getaddrinfo", side_effect=getaddrinfo),
        patch("outwarp.wireguard.socket.getaddrinfo", side_effect=getaddrinfo),
        patch("outwarp.tunnel.verify_tls_fingerprint") as vtf,
        patch("outwarp.tunnel.subprocess.Popen", return_value=fake_proc),
        patch("outwarp.tunnel.get_tunnel_stats", side_effect=_handshake_after_start()),
        patch("outwarp.tunnel.measure_latency_ms", return_value=15),
    ):
        t = Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel"))
        t.connect()

    assert events.index("resolve:vpn.example.org") < events.index("wg-up")
    assert vtf.call_args[0][0] == "vpn.example.org"  # SNI / verified name
    assert vtf.call_args[1]["connect_host"] == "203.0.113.42"


# --- addresses are resolved before WG is up and handed to wstunnel ---

def test_rungs_dial_the_resolved_address_with_the_hostname_as_sni_and_host():
    """Regression: with WG installed (AllowedIPs ≈ 0/0) any lookup wstunnel
    did for itself went into a tunnel that carried nothing yet. Rungs are
    resolved in Python first — system resolver for the plain rung, the public
    one for the force_hostile rung — and wstunnel dials the address while the
    hostname stays on the wire as SNI (what rustls verifies against) and Host
    (what a Caddy front routes on)."""
    from dataclasses import replace

    from outwarp.fallback import strategy_to_command
    from outwarp.tunnel import _with_addresses

    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, endpoint="vpn.example.org", port=8443))
    ladder = build_ladder(cfg)

    def getaddrinfo(host, *a, **k):
        return [(2, 1, 6, "", ("203.0.113.42", 0))]

    with (
        patch("outwarp.tunnel.socket.getaddrinfo", side_effect=getaddrinfo),
        patch("outwarp.tunnel._query_dns_a_record_via", return_value="198.51.100.7") as public,
    ):
        pinned = _with_addresses(ladder)

    by_id = {r.id: r for r in pinned}
    assert by_id["direct"].connect_host == "203.0.113.42"
    assert by_id["direct-hostile"].connect_host == "198.51.100.7"
    public.assert_called_once_with("1.1.1.1", "vpn.example.org")

    cmd = strategy_to_command(by_id["direct"], Path("/usr/bin/wstunnel"), "udp://x")
    assert cmd[-1] == "wss://203.0.113.42:8443"
    assert cmd[cmd.index("--tls-sni-override") + 1] == "vpn.example.org"
    assert "Host: vpn.example.org:8443" in cmd
    cmd = strategy_to_command(by_id["direct-hostile"], Path("/usr/bin/wstunnel"), "udp://x")
    assert cmd[-1] == "wss://198.51.100.7:8443"


def test_hostile_rung_falls_back_to_the_system_resolver_when_the_public_one_is_silent():
    from dataclasses import replace

    from outwarp.tunnel import _with_addresses

    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, endpoint="vpn.example.org"))
    with (
        patch("outwarp.tunnel.socket.getaddrinfo",
              return_value=[(2, 1, 6, "", ("203.0.113.42", 0))]),
        patch("outwarp.tunnel._query_dns_a_record_via", return_value=None),
    ):
        pinned = _with_addresses(build_ladder(cfg))
    assert {r.connect_host for r in pinned} == {"203.0.113.42"}


def test_literal_endpoints_are_left_alone_and_render_unchanged():
    """An IP endpoint (the self-signed default) needs no lookup: no SNI
    override, no Host header beyond wstunnel's own, identical argv to before."""
    from outwarp.fallback import strategy_to_command
    from outwarp.tunnel import _with_addresses

    with patch("outwarp.tunnel._query_dns_a_record_via") as public:
        pinned = _with_addresses(build_ladder(_make_config()))
    public.assert_not_called()
    direct = next(r for r in pinned if r.id == "direct")
    assert direct.connect_host == "203.0.113.42"
    assert not direct.dials_by_address
    cmd = strategy_to_command(direct, Path("/usr/bin/wstunnel"), "udp://x")
    assert "--tls-sni-override" not in cmd
    assert not any(h.startswith("Host:") for h in cmd)
    assert cmd[-1] == "wss://203.0.113.42"


def test_proxy_rung_dials_the_resolved_proxy(monkeypatch):
    from outwarp.tunnel import _with_addresses

    monkeypatch.setenv("HTTPS_PROXY", "http://user:pw@proxy.corp:3128")
    ladder = build_ladder(_make_config())
    with patch("outwarp.tunnel.socket.getaddrinfo",
               return_value=[(2, 1, 6, "", ("10.1.2.3", 0))]):
        pinned = _with_addresses(ladder)
    proxied = next(r for r in pinned if r.proxy)
    assert proxied.proxy == "user:pw@10.1.2.3:3128"


def test_connect_installs_wg_with_every_resolved_address_excluded():
    """The address a rung will dial has to be outside AllowedIPs, or that
    rung's own connection loops into the tunnel. Covers the hostile rung
    resolving to a different address than the system resolver gave."""
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(cfg, server=replace(cfg.server, endpoint="vpn.example.org"),
                  routing=replace(cfg.routing, bypass_ips=[]))
    plat = FakePlatform()
    confs: list[str] = []
    real_install = plat.install_wg_tunnel

    def _install(name, conf):
        confs.append(conf)
        return real_install(name, conf)

    plat.install_wg_tunnel = _install  # type: ignore[method-assign]
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    resolved = [(2, 1, 6, "", ("203.0.113.42", 0))]
    with (
        _apply(_verified_connect_patches(fake_proc)),
        patch("outwarp.tunnel.socket.getaddrinfo", return_value=resolved),
        patch("outwarp.wireguard.socket.getaddrinfo", return_value=resolved),
        patch("outwarp.tunnel._query_dns_a_record_via", return_value="198.51.100.7"),
    ):
        Tunnel(cfg, platform=plat, wstunnel_bin=Path("/fake/wstunnel")).connect()

    import ipaddress
    allowed = next(ln for ln in confs[0].splitlines() if ln.startswith("AllowedIPs"))
    nets = [ipaddress.ip_network(n.strip()) for n in allowed.split("=", 1)[1].split(",")]
    for ip in ("203.0.113.42", "198.51.100.7"):
        assert not any(ipaddress.ip_address(ip) in n for n in nets), (ip, allowed)
    assert any(ipaddress.ip_address("1.1.1.1") in n for n in nets)
