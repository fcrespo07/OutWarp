from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

_APP_NAME = "OutWarp"
_SCHEMA_VERSION = 1
_FINGERPRINT_RE = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServerConfig:
    endpoint: str
    port: int
    http_upgrade_path_prefix: str
    # Alternate WSS ports the server also listens on. Tried in order when the
    # primary `port` is unreachable (a network blocking 443 may still let 8443
    # / 2083 through). Empty = no fallback. The server must actually be
    # listening on these for it to help.
    fallback_ports: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class TlsConfig:
    cert_fingerprint_sha256: str


@dataclass(frozen=True)
class TunnelConfig:
    local_port: int
    remote_host: str
    remote_port: int


@dataclass(frozen=True)
class WireguardConfig:
    tunnel_name: str
    client_address: str
    client_private_key: str
    server_public_key: str
    dns: list[str] = field(default_factory=lambda: ["1.1.1.1"])
    mtu: int = 1380
    # Optional per-peer preshared key (base64). Empty for profiles issued before
    # PSK support — the tunnel still works, just without the extra symmetric
    # layer. Must match the PresharedKey the server set for this peer.
    preshared_key: str = ""


@dataclass(frozen=True)
class RoutingConfig:
    bypass_ips: list[str]


@dataclass(frozen=True)
class ReconnectConfig:
    max_attempts: int = 5
    delays_seconds: list[int] = field(default_factory=lambda: [5, 10, 20, 30, 60])


@dataclass(frozen=True)
class ClientConfig:
    schema_version: int
    server: ServerConfig
    tls: TlsConfig
    tunnel: TunnelConfig
    wireguard: WireguardConfig
    routing: RoutingConfig
    reconnect: ReconnectConfig
    # Human-readable label assigned by the server (outwarp-server add-client <name>).
    # Distinct from wireguard.tunnel_name, which is the OS network interface name.
    name: str = ""
    # ISO date (YYYY-MM-DD) after which the server-issued profile should no
    # longer be used. Empty = never expires. Carried in the .owcfg's "meta"
    # block; surfaced via is_expired() so the UI/CLI can refuse to connect.
    expires_at: str = ""

    def is_expired(self, *, today: str = "") -> bool:
        """True if expires_at is set and strictly before `today` (defaults to the
        current UTC date)."""
        if not self.expires_at:
            return False
        import datetime

        ref = today or datetime.datetime.now(datetime.UTC).date().isoformat()
        return self.expires_at < ref

    @classmethod
    def load(cls, path: Path) -> ClientConfig:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"Config file not found: {path}")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}")
        return _parse(raw)

    @classmethod
    def loads(cls, text: str) -> ClientConfig:
        """Parse an .owcfg from a JSON string, no filesystem round-trip.

        Used by the GUI import path, which receives the file contents over the
        JS bridge — writing them to a temp file just to read them back was both
        slower and a cleanup hazard."""
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Not valid JSON: {exc}") from exc
        return _parse(raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_to_dict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


def default_config_path() -> Path:
    return Path(user_config_dir(_APP_NAME)) / "config.json"


def original_config_path(config_path: Path | None = None) -> Path:
    """Pristine copy of the config as it was imported — the baseline that
    'reset profile settings to defaults' restores from."""
    base = config_path or default_config_path()
    return base.with_name("config.original.json")


def import_owcfg(warpcfg_path: Path, dest: Path | None = None) -> ClientConfig:
    config = ClientConfig.load(warpcfg_path)
    target = dest or default_config_path()
    config.save(target)
    # Snapshot the untouched import so profile editing can always be undone.
    config.save(original_config_path(target))
    return config


def import_owcfg_text(text: str, dest: Path | None = None) -> ClientConfig:
    """Like import_owcfg but from an in-memory string (GUI bridge path)."""
    config = ClientConfig.loads(text)
    target = dest or default_config_path()
    config.save(target)
    config.save(original_config_path(target))
    return config


# --- internal helpers ---

def _require(data: dict[str, Any], key: str, section: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required field '{key}' in section '{section}'")
    return data[key]


def _parse(raw: dict[str, Any]) -> ClientConfig:
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config must be a JSON object, got {type(raw).__name__}"
        )
    version = raw.get("schema_version", 1)
    if version != _SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version {version!r} (expected {_SCHEMA_VERSION}). "
            "Update OutWarp client to a newer version."
        )

    server = _parse_server(_require(raw, "server", "root"))
    tls = _parse_tls(_require(raw, "tls", "root"))
    tunnel = _parse_tunnel(_require(raw, "tunnel", "root"))
    wireguard = _parse_wireguard(_require(raw, "wireguard", "root"))
    routing = _parse_routing(_require(raw, "routing", "root"))
    reconnect = _parse_reconnect(raw.get("reconnect", {}))

    meta = raw.get("meta", {})
    expires_at = str(meta.get("expires_at", "")) if isinstance(meta, dict) else ""

    return ClientConfig(
        schema_version=version,
        server=server,
        tls=tls,
        tunnel=tunnel,
        wireguard=wireguard,
        routing=routing,
        reconnect=reconnect,
        name=str(raw.get("name", "")),
        expires_at=expires_at,
    )


def _parse_server(d: Any) -> ServerConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'server' must be an object")
    endpoint = _require(d, "endpoint", "server")
    port = _require(d, "port", "server")
    prefix = _require(d, "http_upgrade_path_prefix", "server")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"server.port must be an integer between 1 and 65535, got {port!r}")
    fallback_raw = d.get("fallback_ports", [])
    if not isinstance(fallback_raw, list):
        raise ConfigError("server.fallback_ports must be a list of ports")
    fallback_ports: list[int] = []
    for p in fallback_raw:
        if not isinstance(p, int) or not (1 <= p <= 65535):
            raise ConfigError(f"server.fallback_ports entries must be 1-65535, got {p!r}")
        if p != port and p not in fallback_ports:
            fallback_ports.append(p)
    return ServerConfig(
        endpoint=str(endpoint),
        port=port,
        http_upgrade_path_prefix=str(prefix),
        fallback_ports=fallback_ports,
    )


def _parse_tls(d: Any) -> TlsConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'tls' must be an object")
    fp = str(_require(d, "cert_fingerprint_sha256", "tls"))
    if not _FINGERPRINT_RE.match(fp):
        raise ConfigError(
            f"tls.cert_fingerprint_sha256 must be a colon-separated SHA-256 hex string "
            f"(e.g. 'AB:CD:...'), got {fp!r}"
        )
    return TlsConfig(cert_fingerprint_sha256=fp)


def _parse_tunnel(d: Any) -> TunnelConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'tunnel' must be an object")
    local_port = _require(d, "local_port", "tunnel")
    remote_host = _require(d, "remote_host", "tunnel")
    remote_port = _require(d, "remote_port", "tunnel")
    for name, val in (("local_port", local_port), ("remote_port", remote_port)):
        if not isinstance(val, int) or not (1 <= val <= 65535):
            raise ConfigError(f"tunnel.{name} must be an integer between 1 and 65535, got {val!r}")
    return TunnelConfig(
        local_port=local_port,
        remote_host=str(remote_host),
        remote_port=remote_port,
    )


def _parse_wireguard(d: Any) -> WireguardConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'wireguard' must be an object")
    mtu_raw = d.get("mtu", 1380)
    try:
        mtu = int(mtu_raw)
    except (TypeError, ValueError):
        raise ConfigError(f"wireguard.mtu must be an integer, got {mtu_raw!r}")
    if not (576 <= mtu <= 1500):
        raise ConfigError(f"wireguard.mtu must be between 576 and 1500, got {mtu}")
    return WireguardConfig(
        tunnel_name=str(_require(d, "tunnel_name", "wireguard")),
        client_address=str(_require(d, "client_address", "wireguard")),
        client_private_key=str(_require(d, "client_private_key", "wireguard")),
        server_public_key=str(_require(d, "server_public_key", "wireguard")),
        dns=list(d.get("dns", ["1.1.1.1"])),
        mtu=mtu,
        preshared_key=str(d.get("preshared_key", "")),
    )


def _parse_routing(d: Any) -> RoutingConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'routing' must be an object")
    bypass = _require(d, "bypass_ips", "routing")
    if not isinstance(bypass, list) or not all(isinstance(ip, str) for ip in bypass):
        raise ConfigError("routing.bypass_ips must be a list of IP strings")
    return RoutingConfig(bypass_ips=bypass)


def _parse_reconnect(d: Any) -> ReconnectConfig:
    if not isinstance(d, dict):
        return ReconnectConfig()
    return ReconnectConfig(
        max_attempts=int(d.get("max_attempts", 5)),
        delays_seconds=list(d.get("delays_seconds", [5, 10, 20, 30, 60])),
    )


def _to_dict(cfg: ClientConfig) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": cfg.schema_version,
        "name": cfg.name,
        "server": {
            "endpoint": cfg.server.endpoint,
            "port": cfg.server.port,
            "http_upgrade_path_prefix": cfg.server.http_upgrade_path_prefix,
        },
        "tls": {
            "cert_fingerprint_sha256": cfg.tls.cert_fingerprint_sha256,
        },
        "tunnel": {
            "local_port": cfg.tunnel.local_port,
            "remote_host": cfg.tunnel.remote_host,
            "remote_port": cfg.tunnel.remote_port,
        },
        "wireguard": {
            "tunnel_name": cfg.wireguard.tunnel_name,
            "client_address": cfg.wireguard.client_address,
            "client_private_key": cfg.wireguard.client_private_key,
            "server_public_key": cfg.wireguard.server_public_key,
            "dns": cfg.wireguard.dns,
            "mtu": cfg.wireguard.mtu,
        },
        "routing": {
            "bypass_ips": cfg.routing.bypass_ips,
        },
        "reconnect": {
            "max_attempts": cfg.reconnect.max_attempts,
            "delays_seconds": cfg.reconnect.delays_seconds,
        },
    }
    if cfg.server.fallback_ports:
        d["server"]["fallback_ports"] = list(cfg.server.fallback_ports)
    if cfg.wireguard.preshared_key:
        d["wireguard"]["preshared_key"] = cfg.wireguard.preshared_key
    if cfg.expires_at:
        d["meta"] = {"expires_at": cfg.expires_at}
    return d


# --- profile editing ---

# Fields the user is allowed to change from the client UI. Server identity
# (endpoint, port, keys, TLS fingerprint, http_upgrade_path_prefix) is never
# editable — changing it would just break the tunnel, not reconfigure it.
EDITABLE_FIELDS = (
    "name",
    "mtu",
    "dns",
    "client_address",
    "bypass_ips",
    "reconnect_max_attempts",
    "reconnect_delays",
)


def _split_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [tok for tok in re.split(r"[,\s]+", value.strip()) if tok]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    raise ConfigError("se esperaba una lista de valores")


def _parse_ip_list(value: Any, label: str, *, allow_cidr: bool) -> list[str]:
    items = _split_list(value)
    out: list[str] = []
    for item in items:
        try:
            if "/" in item:
                if not allow_cidr:
                    raise ValueError
                ipaddress.ip_network(item, strict=False)
            else:
                ipaddress.ip_address(item)
        except ValueError:
            raise ConfigError(f"{label}: dirección inválida '{item}'")
        out.append(item)
    return out


# RFC 1123 hostname: 1-63-char labels (alnum + hyphen, no leading/trailing
# hyphen) joined by dots, 253 chars total. Used by the bypass list, which the
# runtime resolves at connect time (wireguard._resolve_bypass_networks).
_HOSTNAME_LABEL_RE = re.compile(
    r"^(?=.{1,63}$)[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$"
)


def _is_hostname(value: str) -> bool:
    if not value or len(value) > 253 or value.endswith("."):
        return False
    return all(_HOSTNAME_LABEL_RE.match(lbl) for lbl in value.split("."))


def _parse_endpoint_list(value: Any, label: str) -> list[str]:
    """Like _parse_ip_list(allow_cidr=True) but also accepts hostnames.

    The runtime already resolves hostnames at connect time, so accepting them
    on the editor side lines the validator up with what the tunnel actually
    supports (e.g. a domain endpoint behind dynamic DNS).
    """
    items = _split_list(value)
    out: list[str] = []
    for item in items:
        try:
            if "/" in item:
                ipaddress.ip_network(item, strict=False)
            else:
                ipaddress.ip_address(item)
            out.append(item)
            continue
        except ValueError:
            pass
        if _is_hostname(item):
            out.append(item)
            continue
        raise ConfigError(f"{label}: valor inválido '{item}' (usa una IP, CIDR o dominio)")
    return out


def apply_profile_patch(cfg: ClientConfig, patch: dict[str, Any]) -> ClientConfig:
    """Return a new ClientConfig with the user-editable fields in `patch` applied.

    Raises ConfigError with a human-readable (Spanish) message on bad input so
    the UI can surface it directly.
    """
    name = cfg.name
    wg_changes: dict[str, Any] = {}
    routing = cfg.routing
    rc_changes: dict[str, Any] = {}

    if "name" in patch:
        n = str(patch["name"]).strip()
        if not n:
            raise ConfigError("El nombre del perfil no puede estar vacío")
        name = n

    if "mtu" in patch:
        try:
            mtu = int(patch["mtu"])
        except (TypeError, ValueError):
            raise ConfigError("El MTU debe ser un número entero")
        if not (576 <= mtu <= 1500):
            raise ConfigError("El MTU debe estar entre 576 y 1500")
        wg_changes["mtu"] = mtu

    if "dns" in patch:
        wg_changes["dns"] = _parse_ip_list(patch["dns"], "DNS", allow_cidr=False)

    if "client_address" in patch:
        addr = str(patch["client_address"]).strip()
        try:
            ipaddress.ip_interface(addr)
        except ValueError:
            raise ConfigError(
                f"IP del cliente inválida: '{addr}' (usa formato 10.0.0.2/32)"
            )
        wg_changes["client_address"] = addr

    if "bypass_ips" in patch:
        routing = replace(
            routing,
            bypass_ips=_parse_endpoint_list(patch["bypass_ips"], "Rutas de bypass"),
        )

    if "reconnect_max_attempts" in patch:
        try:
            ma = int(patch["reconnect_max_attempts"])
        except (TypeError, ValueError):
            raise ConfigError("Los reintentos de reconexión deben ser un entero")
        if not (1 <= ma <= 100):
            raise ConfigError("Los reintentos de reconexión deben estar entre 1 y 100")
        rc_changes["max_attempts"] = ma

    if "reconnect_delays" in patch:
        tokens = _split_list(patch["reconnect_delays"])
        if not tokens:
            raise ConfigError("Indica al menos un tiempo de reconexión")
        delays: list[int] = []
        for tok in tokens:
            try:
                v = int(tok)
            except (TypeError, ValueError):
                raise ConfigError(f"Tiempo de reconexión inválido: '{tok}'")
            if v < 1:
                raise ConfigError("Los tiempos de reconexión deben ser positivos")
            delays.append(v)
        rc_changes["delays_seconds"] = delays

    return replace(
        cfg,
        name=name,
        wireguard=replace(cfg.wireguard, **wg_changes) if wg_changes else cfg.wireguard,
        routing=routing,
        reconnect=replace(cfg.reconnect, **rc_changes) if rc_changes else cfg.reconnect,
    )
