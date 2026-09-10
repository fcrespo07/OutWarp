from __future__ import annotations

import ipaddress
from dataclasses import replace

from outwarp.config import (
    ClientConfig,
    FallbackConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    StrategyConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.fallback import build_ladder
from outwarp.routing import escape_set
from outwarp.wireguard import build_wg_conf

VALID_FP = ":".join(["AB"] * 32)


def _cfg(**overrides) -> ClientConfig:
    base = ClientConfig(
        schema_version=1,
        server=ServerConfig(endpoint="wg.example.com", port=443, http_upgrade_path_prefix="s3cret"),
        tls=TlsConfig(cert_fingerprint_sha256=VALID_FP),
        tunnel=TunnelConfig(local_port=51820, remote_host="10.0.0.1", remote_port=51820),
        wireguard=WireguardConfig(
            tunnel_name="OutWarp",
            client_address="10.0.0.42/32",
            client_private_key="xif9YhWWYeCAt6e0GjpNuu9W1952Cagg/0weOOzPL6c=",
            server_public_key="RFUpPmm7W7VHTyjKsHdpR5DV/QICx9UXub9dIMAYZsE=",
        ),
        routing=RoutingConfig(bypass_ips=["203.0.113.42"]),
        reconnect=ReconnectConfig(),
    )
    return replace(base, **overrides)


def test_escape_set_unions_everything(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(
        fallback=FallbackConfig(
            strategies=(
                StrategyConfig(id="cdn", endpoint="front.example.com", bypass_ips=("1.2.3.0/24",)),
            )
        )
    )
    ladder = build_ladder(cfg)
    ips = escape_set(cfg, ladder)
    assert "203.0.113.42" in ips          # routing bypass
    assert "wg.example.com" in ips        # primary endpoint
    assert "front.example.com" in ips     # provisioned rung endpoint
    assert "1.2.3.0/24" in ips            # provisioned rung bypass
    assert len(ips) == len(set(ips))      # de-duplicated


def test_escape_set_empty_ladder_still_excludes_endpoint_and_bypass():
    ips = escape_set(_cfg(), [])
    assert ips == ["203.0.113.42", "wg.example.com"]


def test_kill_switch_allowlist_is_superset_of_wg_conf_exclusions(monkeypatch):
    """CONCEPTO-B invariant (see OutWarp-fix-plan.md): the kill switch
    allowlist and the WireGuard AllowedIPs exclusions must be computed from
    the same escape_set() call. Before the fix, api.py reconstructed a poorer
    version (just routing.bypass_ips) independently — twice — so an address
    the tunnel itself excluded (the server endpoint, an alternate front) could
    still get blocked by the kill switch, trapping the client.

    This asserts the property directly: every plain-IP address in the kill
    switch's allowlist must fall outside every network the resulting
    AllowedIPs actually covers.
    """
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(
        fallback=FallbackConfig(
            strategies=(
                StrategyConfig(id="cdn", endpoint="203.0.113.99", bypass_ips=("198.51.100.0/24",)),
            )
        )
    )
    ladder = build_ladder(cfg)

    kill_switch_allowlist = escape_set(cfg, ladder)  # what api.py._sync_kill_switch uses
    conf = build_wg_conf(cfg, extra_bypass=escape_set(cfg, ladder))  # what tunnel.py installs

    allowed_line = next(line for line in conf.splitlines() if line.startswith("AllowedIPs"))
    allowed_nets = [
        ipaddress.ip_network(n.strip()) for n in allowed_line.split("=", 1)[1].split(",")
    ]

    for addr in kill_switch_allowlist:
        if "/" in addr or not addr[0].isdigit():
            continue  # CIDR ranges and hostnames aren't directly containable-checked here
        ip = ipaddress.ip_address(addr)
        assert not any(ip in net for net in allowed_nets), (
            f"{addr} is in the kill switch allowlist but still covered by AllowedIPs"
        )
