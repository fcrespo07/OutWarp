"""Last-known-address cache: what keeps a hostname endpoint reconnectable
while the kill switch blocks DNS."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from outwarp import dnscache


@pytest.fixture(autouse=True)
def _fresh_cache():
    dnscache.reset_for_tests()
    yield
    dnscache.reset_for_tests()


def test_remember_and_lookup_persist_across_reload(tmp_path: Path) -> None:
    dnscache.remember("vpn.example.org", "203.0.113.7")
    assert dnscache.lookup("vpn.example.org") == "203.0.113.7"
    assert dnscache.cache_path().exists()
    assert tmp_path in dnscache.cache_path().parents  # isolated by conftest
    dnscache.reset_for_tests()
    assert dnscache.lookup("vpn.example.org") == "203.0.113.7"


def test_ignores_empty_values() -> None:
    dnscache.remember("", "1.2.3.4")
    dnscache.remember("host", "")
    assert dnscache.lookup("host") is None
    assert not dnscache.cache_path().exists()


def test_resolve_endpoints_falls_back_to_cache_when_dns_blocked(monkeypatch) -> None:
    from outwarp import tunnel

    dnscache.remember("vpn.example.org", "203.0.113.7")

    def blocked(*a, **k):
        raise OSError("Temporary failure in name resolution")

    monkeypatch.setattr(tunnel.socket, "getaddrinfo", blocked)
    out = tunnel._resolve_endpoints(["vpn.example.org", "198.51.100.1"])
    assert out == {"vpn.example.org": "203.0.113.7", "198.51.100.1": "198.51.100.1"}


def test_resolve_endpoints_records_successful_answers(monkeypatch) -> None:
    from outwarp import tunnel

    monkeypatch.setattr(
        tunnel.socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", 0))],
    )
    assert tunnel._resolve_endpoints(["vpn.example.org"]) == {"vpn.example.org": "203.0.113.9"}
    assert dnscache.lookup("vpn.example.org") == "203.0.113.9"


def test_bypass_networks_fall_back_to_cache(monkeypatch) -> None:
    from outwarp import wireguard

    dnscache.remember("vpn.example.org", "203.0.113.7")

    def blocked(*a, **k):
        raise OSError("blocked")

    monkeypatch.setattr(wireguard.socket, "getaddrinfo", blocked)
    nets = wireguard._resolve_bypass_networks(["vpn.example.org", "10.0.0.0/8"])
    assert [str(n) for n in nets] == ["203.0.113.7/32", "10.0.0.0/8"]


def test_killswitch_allowlist_survives_blocked_dns(monkeypatch) -> None:
    """The regression the 1.0 gate names: hostname endpoint + engaged switch.
    With DNS blocked the allowlist must still carry the server's address, or
    the switch either stays open (silently) or traps the client."""
    from outwarp import killswitch, wireguard
    from outwarp.config import _parse

    profile = {
        "schema_version": 1,
        "server": {"endpoint": "vpn.example.org", "port": 443,
                   "http_upgrade_path_prefix": "x"},
        "tls": {"cert_fingerprint_sha256":
                ("AB:CD:EF:01:23:45:67:89:" * 3) + "AB:CD:EF:01:23:45:67:89"},
        "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
        "wireguard": {
            "tunnel_name": "OutWarp", "client_address": "10.0.0.42/32",
            "client_private_key": "xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
            "server_public_key": "RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
            "dns": ["1.1.1.1"],
        },
        "routing": {"bypass_ips": []},
    }
    config = _parse(profile)
    dnscache.remember("vpn.example.org", "203.0.113.7")

    def blocked(*a, **k):
        raise OSError("blocked by kill switch")

    monkeypatch.setattr(wireguard.socket, "getaddrinfo", blocked)
    allow = killswitch.resolved_allowlist(config)
    assert "203.0.113.7" in allow
