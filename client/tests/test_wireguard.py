from __future__ import annotations

import sys
from unittest.mock import patch

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
from outwarp.wireguard import build_wg_conf


def _make_config(dns: list[str] | None = None) -> ClientConfig:
    return ClientConfig(
        schema_version=1,
        server=ServerConfig(endpoint="203.0.113.42", port=443, http_upgrade_path_prefix="x"),
        tls=TlsConfig(cert_fingerprint_sha256="A" * 95),
        tunnel=TunnelConfig(local_port=51820, remote_host="10.0.0.1", remote_port=51820),
        wireguard=WireguardConfig(
            tunnel_name="OutWarp",
            client_address="10.0.0.42/32",
            client_private_key="cli3ntPriv",
            server_public_key="serv3rPub",
            dns=dns if dns is not None else ["1.1.1.1"],
        ),
        routing=RoutingConfig(bypass_ips=["203.0.113.42"]),
        reconnect=ReconnectConfig(),
    )


def test_build_wg_conf_includes_required_sections():
    text = build_wg_conf(_make_config())
    assert "[Interface]" in text
    assert "[Peer]" in text
    assert "PrivateKey = cli3ntPriv" in text
    assert "PublicKey = serv3rPub" in text


def test_build_wg_conf_endpoint_is_localhost_not_real_server():
    text = build_wg_conf(_make_config())
    assert "Endpoint = 127.0.0.1:51820" in text
    assert "203.0.113.42" not in text  # real endpoint must NOT appear


def test_build_wg_conf_includes_address_and_dns():
    # Pin to the classic openresolv path so the test is environment-agnostic;
    # the systemd-resolved branch is exercised separately below.
    with patch("outwarp.wireguard._systemd_resolved_active", return_value=False):
        text = build_wg_conf(_make_config(dns=["1.1.1.1", "8.8.8.8"]))
    assert "Address = 10.0.0.42/32" in text
    assert "DNS = 1.1.1.1, 8.8.8.8" in text


def test_build_wg_conf_omits_dns_when_empty():
    with patch("outwarp.wireguard._systemd_resolved_active", return_value=False):
        text = build_wg_conf(_make_config(dns=[]))
    assert "DNS" not in text
    assert "resolvectl" not in text


def test_build_wg_conf_uses_resolvectl_when_systemd_resolved_active():
    """Regression for Arch + systemd-resolved: emit PostUp/PreDown hooks that
    drive resolvectl directly, so wg-quick never invokes openresolv's
    resolvconf -a (which aborts with 'signature mismatch' on that setup)."""
    with patch("outwarp.wireguard._systemd_resolved_active", return_value=True):
        text = build_wg_conf(_make_config(dns=["1.1.1.1", "8.8.8.8"]))
    assert "DNS = " not in text
    assert "PostUp = resolvectl dns %i 1.1.1.1 8.8.8.8" in text
    assert "PostUp = resolvectl domain %i ~." in text
    assert "PreDown = resolvectl revert %i" in text


def test_build_wg_conf_resolvectl_skipped_when_no_dns():
    with patch("outwarp.wireguard._systemd_resolved_active", return_value=True):
        text = build_wg_conf(_make_config(dns=[]))
    assert "resolvectl" not in text
    assert "DNS" not in text


def test_build_wg_conf_always_excludes_endpoint_even_without_bypass():
    # Even with an empty bypass list, the server endpoint itself must be carved
    # out of AllowedIPs — otherwise wstunnel's connection to the server would be
    # captured by the tunnel and loop, so the WG handshake never completes.
    cfg = _make_config()
    from dataclasses import replace
    cfg = replace(cfg, routing=RoutingConfig(bypass_ips=[]))
    text = build_wg_conf(cfg)
    assert "AllowedIPs = 0.0.0.0/0" not in text
    assert "203.0.113.42" not in text       # endpoint (203.0.113.42) excluded
    assert "203.0.113.43/32" in text        # neighbouring /32 stays tunneled


def test_build_wg_conf_resolves_domain_endpoint_for_bypass(monkeypatch):
    # A domain endpoint must be resolved to its current IP and excluded; the raw
    # hostname used to reach ipaddress.ip_network() and fail every connect.
    import outwarp.wireguard as wg

    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "wg.example.com"
        return [(2, 1, 6, "", ("198.51.100.42", 0))]

    monkeypatch.setattr(wg.socket, "getaddrinfo", fake_getaddrinfo)
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(
        cfg,
        server=replace(cfg.server, endpoint="wg.example.com"),
        routing=RoutingConfig(bypass_ips=["wg.example.com"]),
    )
    text = build_wg_conf(cfg)
    assert "AllowedIPs = 0.0.0.0/0" not in text
    assert "198.51.100.42" not in text      # resolved endpoint IP excluded
    assert "198.51.100.43/32" in text       # neighbouring /32 stays tunneled


def test_build_wg_conf_excludes_bypass_ips_from_allowed():
    # With bypass IPs, AllowedIPs must cover 0.0.0.0/0 minus the bypass set
    # so wstunnel's own traffic to the server escapes the tunnel.
    text = build_wg_conf(_make_config())  # bypass_ips=["203.0.113.42"]
    assert "AllowedIPs = 0.0.0.0/0" not in text
    assert "203.0.113.42" not in text  # excluded address is not advertised
    # The next /32 is still inside the tunnel — proves we sliced /32-precisely.
    assert "203.0.113.43/32" in text


def test_build_wg_conf_includes_keepalive():
    text = build_wg_conf(_make_config())
    assert "PersistentKeepalive = 25" in text


def test_build_wg_conf_omits_psk_by_default():
    text = build_wg_conf(_make_config())
    assert "PresharedKey" not in text


# ── _systemd_resolved_active detection ─────────────────────────────────────────
#
# Each layout case shims ``Path('/etc/resolv.conf')`` so we can route resolve()
# / read_text() to fixtures without touching real /etc. The function gates on
# Linux + resolvectl-present, so all the tests below run with both shimmed.


@pytest.fixture
def linux_with_resolvectl(monkeypatch):
    """Pretend we're on Linux with `resolvectl` on PATH so the function actually
    runs its layout detection."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("outwarp.wireguard.shutil.which", lambda b: "/usr/bin/resolvectl")


def test_systemd_resolved_detected_via_run_symlink(linux_with_resolvectl, monkeypatch):
    """Canonical Debian/Ubuntu/Arch layout: stub-resolv.conf under /run."""
    monkeypatch.setattr(
        "outwarp.wireguard.Path",
        lambda p: _ResolvePath(p, "/run/systemd/resolve/stub-resolv.conf"),
    )
    from outwarp.wireguard import _systemd_resolved_active
    assert _systemd_resolved_active() is True


def test_systemd_resolved_detected_via_usr_lib_symlink(linux_with_resolvectl, monkeypatch):
    """Fedora/RHEL layout: resolv.conf symlinked to /usr/lib/systemd/resolv.conf
    when systemd-resolved is the active resolver. Previously a false negative
    that defeated the helper's purpose."""
    monkeypatch.setattr(
        "outwarp.wireguard.Path",
        lambda p: _ResolvePath(p, "/usr/lib/systemd/resolv.conf"),
    )
    from outwarp.wireguard import _systemd_resolved_active
    assert _systemd_resolved_active() is True


def test_systemd_resolved_detected_via_loopback_stub_nameserver(
    linux_with_resolvectl, monkeypatch, tmp_path
):
    """Cloud-init / netplan layout: /etc/resolv.conf is a REGULAR FILE that
    points at 127.0.0.53. The function must read the file and accept the
    loopback stub even though there's no symlink to systemd's tree."""
    real_resolv = tmp_path / "resolv.conf"
    real_resolv.write_text(
        "# Generated by NetworkManager / netplan / cloud-init\n"
        "nameserver 127.0.0.53\n"
        "options edns0 trust-ad\n"
    )
    monkeypatch.setattr(
        "outwarp.wireguard.Path",
        lambda p: _ResolvePath(p, str(real_resolv), read_text_source=real_resolv),
    )
    from outwarp.wireguard import _systemd_resolved_active
    assert _systemd_resolved_active() is True


def test_systemd_resolved_not_active_when_nameserver_is_not_loopback(
    linux_with_resolvectl, monkeypatch, tmp_path
):
    """Regular-file resolv.conf with a non-loopback nameserver (e.g. the LAN
    dnsmasq or a public resolver) — NOT systemd-resolved, fall back to the
    classic `DNS = ` line."""
    real_resolv = tmp_path / "resolv.conf"
    real_resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
    monkeypatch.setattr(
        "outwarp.wireguard.Path",
        lambda p: _ResolvePath(p, str(real_resolv), read_text_source=real_resolv),
    )
    from outwarp.wireguard import _systemd_resolved_active
    assert _systemd_resolved_active() is False


def test_systemd_resolved_off_when_resolvectl_missing(monkeypatch):
    """Even on Linux: no resolvectl → can't drive resolved → False, regardless
    of resolv.conf shape."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("outwarp.wireguard.shutil.which", lambda b: None)
    from outwarp.wireguard import _systemd_resolved_active
    assert _systemd_resolved_active() is False


class _ResolvePath:
    """Stand-in for ``pathlib.Path`` that returns a fixed ``resolve()`` target
    and (optionally) reads its text from a different on-disk file. Used to
    exercise the resolv.conf detection branches without touching real /etc."""

    def __init__(self, requested, fake_target: str, *, read_text_source=None):
        from pathlib import Path
        self._requested = str(requested)
        self._fake_target = fake_target
        self._read_source = read_text_source or Path(fake_target)

    def resolve(self):
        return self._fake_target

    def read_text(self, *args, **kwargs):
        from pathlib import Path
        return Path(self._read_source).read_text(*args, **kwargs)


def test_build_wg_conf_includes_psk_when_set():
    from dataclasses import replace
    cfg = _make_config()
    cfg = replace(cfg, wireguard=replace(cfg.wireguard, preshared_key="cHNrMDAw"))
    text = build_wg_conf(cfg)
    assert "PresharedKey = cHNrMDAw" in text
    # PSK belongs to the [Peer] section, after the peer's PublicKey.
    assert text.index("PublicKey = serv3rPub") < text.index("PresharedKey")
