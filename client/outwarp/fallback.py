"""Connection fallback ladder.

OutWarp connects "almost always" on hostile networks by trying a sequence of
transport *strategies* until one actually carries traffic, instead of a single
attempt. The WireGuard layer is invariant across strategies — it always talks to
127.0.0.1:<local_port> — so only the wstunnel front changes between rungs. The
ladder therefore brings WireGuard up once and just relaunches wstunnel per rung
(see outwarp.tunnel.Tunnel.connect).

A rung is only accepted when a WireGuard handshake completes AND a ping goes
through the tunnel; a live wstunnel process alone is not proof (the exact
institute failure was "process up but every WS upgrade 400s → RX=0").

Rung order (probability × cleanliness):

    S0 direct                      — current behaviour
    S1 direct + hostile DNS flags  — 1.1.1.1 + IPv4-only (poisoned DNS / broken v6)
    S2 direct + browser User-Agent — cheap L7 camouflage
    S3 via HTTP proxy              — only if a proxy is configured/detected
    S4 alternate WSS ports         — from server.fallback_ports
    S5.. server-provisioned        — CDN front, SNI override, no-pin, etc.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from outwarp.config import ClientConfig, StrategyConfig

log = logging.getLogger(__name__)

# A common desktop-Chrome UA. The point of S2 is to stop looking like the
# fingerprint-less default request; the exact string only needs to be plausible.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Env vars wstunnel/curl-style tooling honours for an outbound HTTP proxy.
_PROXY_ENV_VARS = (
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
)


@dataclass(frozen=True)
class ConnectionStrategy:
    """One fully-resolved rung of the ladder — a concrete wstunnel invocation."""

    id: str
    label: str
    endpoint: str
    port: int
    path_prefix: str
    scheme: str = "wss"  # wss | ws
    force_hostile: bool = False
    sni_override: str = ""
    host_header: str = ""
    user_agent: str = ""
    proxy: str = ""
    pin_mode: str = "pin"  # pin | tolerate | none
    # Extra IPs/CIDRs/hostnames this rung's endpoint needs excluded from the
    # tunnel (e.g. a CDN's anycast ranges). The endpoint itself is added by the
    # caller; this is for fronts that resolve to a different address than the URL.
    bypass_ips: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        default = 443 if self.scheme == "wss" else 80
        if self.port == default:
            return f"{self.scheme}://{self.endpoint}"
        return f"{self.scheme}://{self.endpoint}:{self.port}"

    @property
    def dedup_key(self) -> tuple:
        return (
            self.endpoint,
            self.port,
            self.scheme,
            self.force_hostile,
            self.sni_override,
            self.user_agent,
            self.proxy,
            self.pin_mode,
            self.path_prefix,
        )


def strategy_to_command(
    strategy: ConnectionStrategy, wstunnel_bin: Path, forward: str
) -> list[str]:
    """Render a wstunnel client argv for `strategy`."""
    cmd = [
        str(wstunnel_bin),
        "client",
        "--connection-min-idle",
        "3",
        "--websocket-ping-frequency",
        "25s",
        "-L",
        forward,
        "--http-upgrade-path-prefix",
        strategy.path_prefix,
    ]
    if strategy.force_hostile:
        cmd.extend(["--dns-resolver", "dns://1.1.1.1", "--dns-resolver-prefer-ipv4"])
    if strategy.sni_override:
        cmd.extend(["--tls-sni-override", strategy.sni_override])
    headers: list[str] = []
    if strategy.host_header:
        headers.append(f"Host: {strategy.host_header}")
    if strategy.user_agent:
        headers.append(f"User-Agent: {strategy.user_agent}")
    for h in headers:
        cmd.extend(["--http-headers", h])
    if strategy.proxy:
        cmd.extend(["--http-proxy", strategy.proxy])
    cmd.append(strategy.url)
    return cmd


def _detect_system_proxy() -> str:
    for var in _PROXY_ENV_VARS:
        val = os.environ.get(var, "").strip()
        if val:
            # wstunnel's --http-proxy wants USER:PASS@HOST:PORT; strip a scheme
            # prefix if the env var carried one (http://host:port).
            return val.split("://", 1)[-1]
    return ""


def build_ladder(config: ClientConfig) -> list[ConnectionStrategy]:
    """Compose the ordered list of strategies to try for `config`.

    Client-side defaults (S0–S4) are generated from the primary server config,
    then merged with any server-provisioned strategies from the .owcfg. Rungs
    whose precondition is statically unmet (no proxy, no alt ports) are omitted
    so the ladder never wastes a slot on something that cannot apply. Duplicates
    (same endpoint+transport) are collapsed, first occurrence wins.
    """
    s = config.server
    prefix = s.http_upgrade_path_prefix
    hostile_mode = config.network.hostile_mode
    rungs: list[ConnectionStrategy] = []

    def _direct(sid: str, label: str, **kw: Any) -> ConnectionStrategy:
        return ConnectionStrategy(
            id=sid, label=label, endpoint=s.endpoint, port=s.port, path_prefix=prefix, **kw
        )

    # S0 plain direct. Skipped when the user forced hostile mode on — no point
    # trying the non-hostile variant first if they already know the network is
    # hostile.
    if hostile_mode != "on":
        rungs.append(_direct("direct", "Direct"))
    # S1 direct + hostile DNS flags. Always present (this is the legacy's proven
    # behaviour). When hostile_mode == "off" the user opted out of the DNS
    # bypass, so we still keep it as a *fallback* rung but it comes after S0.
    rungs.append(_direct("direct-hostile", "Direct (public DNS)", force_hostile=True))
    # S2 direct + browser camouflage.
    rungs.append(
        _direct(
            "direct-camouflage",
            "Direct (browser headers)",
            force_hostile=True,
            user_agent=DEFAULT_USER_AGENT,
        )
    )

    # S3 via HTTP proxy, only if one is configured in the environment.
    proxy = _detect_system_proxy()
    if proxy:
        rungs.append(
            _direct("direct-proxy", "Via HTTP proxy", force_hostile=True, proxy=proxy)
        )

    # S4 alternate WSS ports. Scheme stays wss; 80 is treated as ws only when a
    # server explicitly provisions it (below), never guessed here.
    for alt in s.fallback_ports:
        rungs.append(
            ConnectionStrategy(
                id=f"port-{alt}",
                label=f"Alt port {alt}",
                endpoint=s.endpoint,
                port=alt,
                path_prefix=prefix,
                force_hostile=True,
            )
        )

    # S5.. server-provisioned rungs (CDN front, SNI override, proxy, …).
    for sc in config.fallback.strategies:
        rungs.append(_resolve_provisioned(sc, config))

    # De-dup, first occurrence wins.
    out: list[ConnectionStrategy] = []
    seen: set[tuple] = set()
    for r in rungs:
        if r.dedup_key in seen:
            continue
        seen.add(r.dedup_key)
        out.append(r)
    return out


def _resolve_provisioned(sc: StrategyConfig, config: ClientConfig) -> ConnectionStrategy:
    s = config.server
    endpoint = sc.endpoint or s.endpoint
    default_port = 443 if sc.scheme == "wss" else 80
    port = sc.port or (s.port if sc.scheme == "wss" else default_port)
    return ConnectionStrategy(
        id=sc.id,
        label=sc.id.replace("-", " ").replace("_", " ").title(),
        endpoint=endpoint,
        port=port,
        path_prefix=sc.path_prefix or s.http_upgrade_path_prefix,
        scheme=sc.scheme,
        force_hostile=sc.force_hostile,
        sni_override=sc.sni_override,
        host_header=sc.host_header,
        user_agent=sc.user_agent,
        proxy=sc.proxy,
        pin_mode=sc.pin_mode,
        bypass_ips=tuple(sc.bypass_ips),
    )


def reorder_for_sticky(
    ladder: list[ConnectionStrategy], sticky_id: str
) -> list[ConnectionStrategy]:
    """Move the strategy that last worked on this network to the front.

    Returns a new list; the relative order of the remaining rungs is preserved
    so the ladder still escalates sensibly if the sticky rung fails.
    """
    if not sticky_id:
        return list(ladder)
    preferred = [r for r in ladder if r.id == sticky_id]
    rest = [r for r in ladder if r.id != sticky_id]
    return preferred + rest


def all_bypass_ips(config: ClientConfig, ladder: list[ConnectionStrategy]) -> list[str]:
    """Union of every address that must stay outside the tunnel across all rungs.

    WireGuard is installed once with this union excluded, so switching rungs
    never needs a live route change: whichever front a rung dials, its traffic
    already escapes the tunnel.
    """
    out: list[str] = list(config.routing.bypass_ips)
    if config.server.endpoint:
        out.append(config.server.endpoint)
    for r in ladder:
        if r.endpoint:
            out.append(r.endpoint)
        out.extend(r.bypass_ips)
    # De-dup preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for ip in out:
        if ip and ip not in seen:
            seen.add(ip)
            deduped.append(ip)
    return deduped


# ── sticky store: remember which rung worked per network ────────────────────


def _first_nameserver() -> str:
    if sys.platform == "win32":
        return ""
    try:
        text = Path("/etc/resolv.conf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return ""


def network_signature(gateway: str = "") -> str:
    """Cheap, best-effort fingerprint of the current network.

    Not unique or secure — just stable enough to recognise "the same Wi-Fi as
    last time" so the sticky store can start from the rung that worked. Combines
    the default gateway with the system's first configured nameserver. Returns
    "" when nothing identifying is available (then stickiness is simply skipped).
    """
    resolver = _first_nameserver()
    parts = [p for p in (gateway, resolver) if p]
    return "|".join(parts)


@dataclass
class StickyStore:
    """Persists network_signature → last-good strategy id as flat JSON."""

    path: Path
    _data: dict[str, str] = field(default_factory=dict)
    _loaded: bool = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {str(k): str(v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def get(self, signature: str) -> str:
        if not signature:
            return ""
        self._load()
        return self._data.get(signature, "")

    def set(self, signature: str, strategy_id: str) -> None:
        if not signature or not strategy_id:
            return
        self._load()
        if self._data.get(signature) == strategy_id:
            return
        self._data[signature] = strategy_id
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.debug("Could not persist sticky strategy store: %s", exc)


def default_sticky_path() -> Path:
    from platformdirs import user_config_dir

    return Path(user_config_dir("OutWarp")) / "network_strategies.json"
