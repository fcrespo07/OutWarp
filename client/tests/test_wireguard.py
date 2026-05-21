from __future__ import annotations

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
    text = build_wg_conf(_make_config(dns=["1.1.1.1", "8.8.8.8"]))
    assert "Address = 10.0.0.42/32" in text
    assert "DNS = 1.1.1.1, 8.8.8.8" in text


def test_build_wg_conf_omits_dns_when_empty():
    text = build_wg_conf(_make_config(dns=[]))
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
