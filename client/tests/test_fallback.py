from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from outwarp.config import (
    ClientConfig,
    FallbackConfig,
    NetworkConfig,
    ReconnectConfig,
    RoutingConfig,
    ServerConfig,
    StrategyConfig,
    TlsConfig,
    TunnelConfig,
    WireguardConfig,
)
from outwarp.fallback import (
    ConnectionStrategy,
    StickyStore,
    all_bypass_ips,
    build_ladder,
    network_signature,
    reorder_for_sticky,
    strategy_to_command,
)

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
            client_private_key="priv",
            server_public_key="pub",
        ),
        routing=RoutingConfig(bypass_ips=["203.0.113.42"]),
        reconnect=ReconnectConfig(),
    )
    return replace(base, **overrides)


# --- build_ladder ---

def test_ladder_default_rungs(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    ladder = build_ladder(_cfg())
    assert [r.id for r in ladder] == ["direct", "direct-hostile"]
    # S0 is plain, S1 forces the public-DNS flags.
    assert ladder[0].force_hostile is False
    assert ladder[1].force_hostile is True


def test_every_direct_rung_sends_a_browser_user_agent(monkeypatch):
    """Camouflage used to be its own rung, which meant paying a whole failed
    attempt for it and only reaching L7 filters on the third try."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    cfg = _cfg(server=replace(_cfg().server, fallback_ports=[8443]))
    ladder = build_ladder(cfg)
    assert all(r.user_agent for r in ladder)
    assert "direct-camouflage" not in [r.id for r in ladder]


def test_ladder_hostile_on_drops_plain_direct(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(network=NetworkConfig(hostile_mode="on"))
    ladder = build_ladder(cfg)
    assert "direct" not in [r.id for r in ladder]
    assert ladder[0].id == "direct-hostile"


def test_ladder_includes_alt_ports(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(server=replace(_cfg().server, fallback_ports=[8443]))
    ladder = build_ladder(cfg)
    port_rungs = [r for r in ladder if r.id == "port-8443"]
    assert len(port_rungs) == 1
    assert port_rungs[0].port == 8443
    assert port_rungs[0].force_hostile is True


def test_ladder_adds_proxy_rung_when_env_set(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:3128")
    ladder = build_ladder(_cfg())
    proxy_rungs = [r for r in ladder if r.id == "direct-proxy"]
    assert len(proxy_rungs) == 1
    # Scheme prefix is stripped for wstunnel's --http-proxy USER:PASS@HOST:PORT.
    assert proxy_rungs[0].proxy == "proxy.local:3128"


def test_ladder_appends_server_provisioned(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(
        fallback=FallbackConfig(
            strategies=(
                StrategyConfig(
                    id="cdn",
                    endpoint="front.example.com",
                    pin_mode="none",
                    force_hostile=True,
                    bypass_ips=("188.114.96.0/20",),
                ),
            )
        )
    )
    ladder = build_ladder(cfg)
    cdn = [r for r in ladder if r.id == "cdn"]
    assert len(cdn) == 1
    assert cdn[0].endpoint == "front.example.com"
    assert cdn[0].port == 443  # inherited from primary
    assert cdn[0].pin_mode == "none"
    assert cdn[0].path_prefix == "s3cret"  # inherited


def test_ladder_dedups_identical_rungs(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    # A provisioned rung identical to the default direct one collapses.
    cfg = _cfg(fallback=FallbackConfig(strategies=(StrategyConfig(id="dup"),)))
    ladder = build_ladder(cfg)
    assert [r.id for r in ladder].count("dup") == 0  # collapsed into "direct"


# --- strategy_to_command ---

def _strat(**kw) -> ConnectionStrategy:
    base = {"id": "x", "label": "X", "endpoint": "h.example", "port": 443, "path_prefix": "pfx"}
    base.update(kw)
    return ConnectionStrategy(**base)


def test_command_default_omits_443_and_dns_flags():
    cmd = strategy_to_command(_strat(), Path("/bin/wstunnel"), "udp://x")
    assert cmd[-1] == "wss://h.example"
    assert "--dns-resolver" not in cmd
    assert cmd[cmd.index("--http-upgrade-path-prefix") + 1] == "pfx"


def test_command_hostile_adds_dns_flags():
    cmd = strategy_to_command(_strat(force_hostile=True), Path("/bin/wstunnel"), "udp://x")
    assert cmd[cmd.index("--dns-resolver") + 1] == "dns://1.1.1.1"
    assert "--dns-resolver-prefer-ipv4" in cmd


def test_command_sni_and_headers_and_proxy():
    cmd = strategy_to_command(
        _strat(
            sni_override="www.microsoft.com",
            host_header="front.example.com",
            user_agent="Mozilla/5.0",
            proxy="proxy:3128",
        ),
        Path("/bin/wstunnel"),
        "udp://x",
    )
    assert cmd[cmd.index("--tls-sni-override") + 1] == "www.microsoft.com"
    headers = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--http-headers"]
    assert "Host: front.example.com" in headers
    assert "User-Agent: Mozilla/5.0" in headers
    assert cmd[cmd.index("--http-proxy") + 1] == "proxy:3128"


def test_command_ws_scheme_omits_default_80():
    cmd = strategy_to_command(_strat(scheme="ws", port=80), Path("/bin/wstunnel"), "udp://x")
    assert cmd[-1] == "ws://h.example"


# --- reorder_for_sticky / all_bypass_ips ---

def test_reorder_for_sticky_moves_match_to_front():
    ladder = [_strat(id="a"), _strat(id="b"), _strat(id="c")]
    out = reorder_for_sticky(ladder, "c")
    assert [r.id for r in out] == ["c", "a", "b"]


def test_reorder_for_sticky_empty_is_noop():
    ladder = [_strat(id="a"), _strat(id="b")]
    assert [r.id for r in reorder_for_sticky(ladder, "")] == ["a", "b"]


def test_all_bypass_ips_unions_everything(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    cfg = _cfg(
        fallback=FallbackConfig(
            strategies=(
                StrategyConfig(id="cdn", endpoint="front.example.com", bypass_ips=("1.2.3.0/24",)),
            )
        )
    )
    ladder = build_ladder(cfg)
    ips = all_bypass_ips(cfg, ladder)
    assert "203.0.113.42" in ips          # routing bypass
    assert "wg.example.com" in ips        # primary endpoint
    assert "front.example.com" in ips     # provisioned rung endpoint
    assert "1.2.3.0/24" in ips            # provisioned rung bypass
    assert len(ips) == len(set(ips))      # de-duplicated


# --- StickyStore / network_signature ---

def test_sticky_store_roundtrip(tmp_path):
    store = StickyStore(tmp_path / "sticky.json")
    assert store.get("net-a") == ""
    store.set("net-a", "direct-hostile")
    assert store.get("net-a") == "direct-hostile"
    # A fresh instance reads it back from disk.
    assert StickyStore(tmp_path / "sticky.json").get("net-a") == "direct-hostile"


def test_sticky_store_ignores_empty(tmp_path):
    store = StickyStore(tmp_path / "sticky.json")
    store.set("", "direct")
    store.set("net", "")
    assert not (tmp_path / "sticky.json").exists()


def test_network_signature_combines_gateway_and_resolver(monkeypatch):
    monkeypatch.setattr("outwarp.fallback._first_nameserver", lambda: "192.168.1.1")
    assert network_signature("10.0.0.1") == "10.0.0.1|192.168.1.1"


def test_network_signature_empty_when_nothing_known(monkeypatch):
    monkeypatch.setattr("outwarp.fallback._first_nameserver", lambda: "")
    assert network_signature("") == ""


# --- config round-trip of the fallback block ---

def test_config_fallback_roundtrip(tmp_path):
    cfg = _cfg(
        fallback=FallbackConfig(
            strategies=(
                StrategyConfig(id="cdn", endpoint="f.example", pin_mode="none", force_hostile=True),
            )
        )
    )
    out = tmp_path / "c.json"
    cfg.save(out)
    reloaded = ClientConfig.load(out)
    assert reloaded.fallback.strategies[0].id == "cdn"
    assert reloaded.fallback.strategies[0].pin_mode == "none"
    assert reloaded.fallback.strategies[0].force_hostile is True


def test_config_fallback_rejects_bad_pin_mode(tmp_path):
    from outwarp.config import ConfigError, _parse

    raw = {
        "schema_version": 1,
        "server": {"endpoint": "e", "port": 443, "http_upgrade_path_prefix": "p"},
        "tls": {"cert_fingerprint_sha256": VALID_FP},
        "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
        "wireguard": {
            "tunnel_name": "OutWarp",
            "client_address": "10.0.0.42/32",
            "client_private_key": "k",
            "server_public_key": "k",
        },
        "routing": {"bypass_ips": []},
        "fallback": {"strategies": [{"id": "x", "pin_mode": "bogus"}]},
    }
    with pytest.raises(ConfigError, match="pin_mode"):
        _parse(raw)


# --- CA-mode rungs (schema v2 / ACME server branch) ---

def test_ca_profile_marks_client_rungs_ca(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    cfg = _cfg(
        tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"),
        server=ServerConfig(
            endpoint="wg.example.com", port=443,
            http_upgrade_path_prefix="s3cret", fallback_ports=[8443],
        ),
    )
    ladder = build_ladder(cfg)
    assert {r.pin_mode for r in ladder} == {"ca"}


def test_pin_profile_keeps_client_rungs_on_pin(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    assert {r.pin_mode for r in build_ladder(_cfg())} == {"pin"}


def test_provisioned_rung_keeps_its_own_trust_mode():
    # A CDN front is a different server with a different certificate, so its
    # pin_mode must not be overwritten by the profile's.
    cfg = _cfg(
        tls=TlsConfig(cert_fingerprint_sha256="", verify="ca"),
        fallback=FallbackConfig(
            strategies=(StrategyConfig(id="cdn", endpoint="cdn.example.net", pin_mode="none"),)
        ),
    )
    cdn = next(r for r in build_ladder(cfg) if r.id == "cdn")
    assert cdn.pin_mode == "none"


def test_ca_rung_asks_wstunnel_to_verify():
    strat = ConnectionStrategy(
        id="direct", label="Direct", endpoint="wg.example.com", port=443,
        path_prefix="s3cret", pin_mode="ca",
    )
    cmd = strategy_to_command(strat, Path("/usr/bin/wstunnel"), "udp://51820:10.0.0.1:51820")
    assert "--tls-verify-certificate" in cmd


@pytest.mark.parametrize("mode", ["pin", "tolerate", "none"])
def test_non_ca_rungs_do_not_pass_the_verify_flag(mode):
    # wstunnel's own verification is against the system CA store, which a
    # self-signed server can never satisfy — passing it there would break
    # every pinned profile.
    strat = ConnectionStrategy(
        id="direct", label="Direct", endpoint="wg.example.com", port=443,
        path_prefix="s3cret", pin_mode=mode,
    )
    cmd = strategy_to_command(strat, Path("/usr/bin/wstunnel"), "udp://51820:10.0.0.1:51820")
    assert "--tls-verify-certificate" not in cmd
