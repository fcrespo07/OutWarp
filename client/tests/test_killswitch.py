from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

from outwarp.config import (
    ClientConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.killswitch import reconcile, resolved_allowlist
from outwarp.routing import proxy_host
from outwarp.tunnel import TunnelState


def _cfg(endpoint: str = "203.0.113.42", bypass: list[str] | None = None) -> ClientConfig:
    return ClientConfig(
        schema_version=1,
        server=ServerConfig(endpoint=endpoint, port=443, http_upgrade_path_prefix="x"),
        tls=TlsConfig(cert_fingerprint_sha256="A" * 95),
        tunnel=TunnelConfig(local_port=51820, remote_host="10.0.0.1", remote_port=51820),
        wireguard=WireguardConfig(
            tunnel_name="OutWarp", client_address="10.9.0.4/32",
            client_private_key="priv", server_public_key="pub",
        ),
        routing=RoutingConfig(bypass_ips=bypass if bypass is not None else [endpoint]),
        reconnect=ReconnectConfig(),
    )


def test_resolved_allowlist_turns_hostnames_into_addresses():
    """Regression: a domain endpoint reached the firewall helper unresolved,
    was rejected as an invalid IPv4, and the switch silently never engaged
    for every domain-based profile."""
    cfg = _cfg(endpoint="vpn.example.org", bypass=["vpn.example.org", "198.51.100.0/24"])
    infos = [(2, 1, 6, "", ("203.0.113.9", 0))]
    with patch("outwarp.wireguard.socket.getaddrinfo", return_value=infos):
        allow = resolved_allowlist(cfg)
    assert "vpn.example.org" not in allow
    assert "203.0.113.9" in allow
    assert "198.51.100.0/24" in allow


def test_resolved_allowlist_matches_wireguard_exclusion():
    """Kill switch allowlist and AllowedIPs exclusion must come from the same
    resolver so the two can never disagree."""
    from outwarp.fallback import build_ladder
    from outwarp.routing import escape_set
    from outwarp.wireguard import _resolve_bypass_networks

    cfg = _cfg()
    expected = [str(n.network_address) for n in
                _resolve_bypass_networks(escape_set(cfg, build_ladder(cfg)))]
    assert resolved_allowlist(cfg) == expected


def test_reconcile_refuses_to_engage_when_allowlist_is_empty():
    cfg = _cfg()
    plat = MagicMock()
    with patch("outwarp.killswitch.resolved_allowlist", return_value=[]), \
         patch("outwarp.killswitch.get_platform", return_value=plat):
        reconcile(cfg, TunnelState.FAILED)
    plat.engage_kill_switch.assert_not_called()


def test_reconcile_still_engages_via_hostile_resolver_when_endpoint_dns_fails():
    """S1 (direct-hostile) is always in the ladder, so 1.1.1.1 — the resolver
    a hostile rung bootstraps itself with — always escapes the tunnel, even
    when the profile's own endpoint hostname can't be resolved at all. The
    kill switch should still engage rather than give up on protection."""
    cfg = _cfg(endpoint="nowhere.invalid", bypass=["nowhere.invalid"])
    plat = MagicMock()
    with patch("outwarp.wireguard.socket.getaddrinfo", side_effect=OSError("nxdomain")), \
         patch("outwarp.killswitch.get_platform", return_value=plat):
        reconcile(cfg, TunnelState.FAILED)
    plat.engage_kill_switch.assert_called_once_with(
        ["1.1.1.1"], tunnel_iface="OutWarp", tunnel_address="10.9.0.4",
    )


def test_reconcile_passes_interface_and_address():
    cfg = _cfg()
    plat = MagicMock()
    with patch("outwarp.killswitch.get_platform", return_value=plat):
        reconcile(cfg, TunnelState.RECONNECTING)
    plat.engage_kill_switch.assert_called_once_with(
        ["203.0.113.42", "1.1.1.1"], tunnel_iface="OutWarp", tunnel_address="10.9.0.4",
    )


def test_proxy_host_parsing():
    assert proxy_host("proxy.corp:3128") == "proxy.corp"
    assert proxy_host("user:pw@10.1.2.3:8080") == "10.1.2.3"
    assert proxy_host("[2001:db8::1]:8080") == "2001:db8::1"
    assert proxy_host("bare-host") == "bare-host"


def test_escape_set_includes_proxy_host():
    from outwarp.fallback import ConnectionStrategy, build_ladder
    from outwarp.routing import escape_set

    cfg = _cfg()
    ladder = build_ladder(cfg)
    base = ladder[0]
    proxied = replace(base, id="direct-proxy", proxy="user:pw@proxy.corp:3128")
    assert isinstance(proxied, ConnectionStrategy)
    assert "proxy.corp" in escape_set(cfg, ladder + [proxied])
