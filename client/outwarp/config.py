from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platformdirs import user_config_dir

if TYPE_CHECKING:
    from outwarp import profile_trust

_APP_NAME = "OutWarp"
# v2 added tls.verify / tls.spki_sha256 (the ACME + Caddy server branch).
# v3 replaced wireguard.client_private_key with an enrolment token: the client
# generates its own keypair and registers the public half.
# v4 moved the token redemption onto the tunnel port (enrollment.remote_port
# instead of a public enrollment.url on a second port). Older profiles stay
# valid forever — the parser accepts anything up to this number, so a server can
# keep issuing v1/v2 .owcfg files that older clients also read.
_SCHEMA_VERSION = 4
_FINGERPRINT_RE = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")
_TLS_VERIFY_MODES = ("pin", "ca")
# A WireGuard base64 key/PSK is always 44 chars, the last one from a fixed
# small alphabet (the encoded value's top 2 bits are always zero). Mirrors
# server/outwarp_server/enroll_server.py:_WG_KEY_RE — keep the two in sync.
_WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")
# Linux interface names are capped at IFNAMSIZ-1 = 15 bytes; wg-quick fails
# outright above that, so this also doubles as an early, clear error.
_TUNNEL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,15}$")

# CONCEPTO-C prop.1 (OutWarp-fix-plan.md): the .owcfg is hostile input — it
# travels by email, USB or messaging, and its "signing" block (profile_trust.py)
# is opt-in TOFU, not a hard gate. Every field that reaches a subprocess
# argument, an HTTP header, or a line written into a config file needs an
# explicit validation decision at parse time, the same way WireGuard keys and
# IPs already get one — a bare str(...) passthrough is a decision too, just
# the wrong one, and it's the default this policy exists to remove. The two
# checks below cover what the structural regexes elsewhere in this module
# don't: host-shaped strings (via _is_hostname, defined further down —
# forward references between module-level functions resolve fine, they're
# only ever called after the whole module has loaded), and free text that
# must not carry embedded control characters into a subprocess arg or HTTP
# header value.

# The wstunnel upgrade path prefix and the fallback ladder's own path_prefix
# both end up as one argv element (--restrict-http-upgrade-path-prefix /
# --http-upgrade-path-prefix) and, on the server side, a Caddyfile path
# matcher — no slashes, spaces or control characters.
_PATH_PREFIX_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _is_valid_host(value: str) -> bool:
    """Whether `value` is shaped like an IP address or a hostname.

    Reuses _is_hostname (below) rather than a second regex — that function
    already backs routing.bypass_ips' domain-or-IP acceptance.
    """
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return _is_hostname(value)


def _has_control_chars(value: str) -> bool:
    """Whether `value` contains a C0 control character (incl. CR/LF/NUL).

    None of this project's free-text fields (User-Agent, Host header, SNI
    override, path prefix, proxy URL...) are legitimately multi-line — a
    control character in one is either a malformed profile or an attempt to
    inject a second HTTP header / config line into whatever the value gets
    interpolated into downstream.
    """
    return any(ord(ch) < 0x20 for ch in value)


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
    """How the client authenticates the outer TLS layer of the transport.

    ``verify == "pin"`` (the default, and everything issued before v2) trusts one
    specific server: the self-signed certificate it was handed at enrolment, and
    nothing else. ``verify == "ca"`` is for a server sitting behind a real
    certificate — the chain is validated against the system trust store instead,
    which is the only mode that survives a Let's Encrypt renewal and the only one
    wstunnel can also enforce in-band (``--tls-verify-certificate``).

    In pin mode ``spki_sha256`` takes precedence when present: pinning the public
    key instead of the whole certificate lets the server reissue without
    invalidating every .owcfg already distributed.
    """

    cert_fingerprint_sha256: str
    verify: str = "pin"
    spki_sha256: str = ""

    @property
    def pin_value(self) -> str:
        return self.spki_sha256 or self.cert_fingerprint_sha256


@dataclass(frozen=True)
class TunnelConfig:
    local_port: int
    remote_host: str
    remote_port: int


@dataclass(frozen=True)
class EnrollmentConfig:
    """Present on an enrolment profile until the token has been redeemed.

    ``token`` is single-use and short-lived; it is cleared once enrolment
    succeeds, so a saved profile never keeps a spent credential. Its presence
    alongside an empty ``wireguard.client_private_key`` is what tells the import
    path there is a key to generate first.

    Where to redeem it depends on the schema. v4 carries ``remote_port``: the
    loopback port on the server the client reaches as a wstunnel TCP forward
    over the tunnel port it already has, so enrolment needs no port of its own
    (B-018). v3 carried a public HTTPS ``url`` on a second port instead; still
    honoured so a profile from an older server keeps importing.
    """

    token: str = ""
    url: str = ""
    remote_port: int = 0


@dataclass(frozen=True)
class WireguardConfig:
    tunnel_name: str
    client_address: str
    # Empty on a freshly-issued v3 profile: the client fills it in from a locally
    # generated key during enrolment, and it never travels anywhere.
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
class NetworkConfig:
    # Hostile-network mode controls whether the wstunnel client uses an explicit
    # public DNS resolver + IPv4-only resolution. "auto" probes the network at
    # connect time and switches behaviour transparently; "on"/"off" force it.
    # Why: captive/edu/corp networks frequently intercept DNS or poison AAAA
    # responses, which kills the tunnel before the WS upgrade even starts.
    hostile_mode: str = "auto"


@dataclass(frozen=True)
class StrategyConfig:
    """A server-provisioned extra rung for the connection fallback ladder.

    Everything except ``id`` is optional and inherits from the primary server
    config when left blank: an empty ``endpoint``/``port`` means "same as the
    direct path". Populated by the server admin who knows what alternate fronts
    exist (a CDN-fronted hostname, an open alt port, a proxy). The client always
    generates its own default rungs on top of these — see
    outwarp.fallback.build_ladder.
    """

    id: str
    endpoint: str = ""
    port: int = 0
    scheme: str = "wss"  # wss | ws
    sni_override: str = ""
    host_header: str = ""
    user_agent: str = ""
    path_prefix: str = ""
    proxy: str = ""
    # pin | tolerate | none — how the outer-TLS fingerprint pin is enforced for
    # this rung. A CDN front rotates its cert, so it uses "none" and relies on
    # WireGuard key auth as the security boundary.
    pin_mode: str = "pin"
    force_hostile: bool = False
    bypass_ips: tuple[str, ...] = ()


@dataclass(frozen=True)
class FallbackConfig:
    enabled: bool = True
    strategies: tuple[StrategyConfig, ...] = ()


@dataclass(frozen=True)
class ClientConfig:
    schema_version: int
    server: ServerConfig
    tls: TlsConfig
    tunnel: TunnelConfig
    wireguard: WireguardConfig
    routing: RoutingConfig
    reconnect: ReconnectConfig
    network: NetworkConfig = field(default_factory=NetworkConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
    enrollment: EnrollmentConfig = field(default_factory=EnrollmentConfig)
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
        except FileNotFoundError as exc:
            raise ConfigError(f"Config file not found: {path}") from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}") from exc
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
        # config.json holds the client's WireGuard private key. Write it
        # atomically at 0o600 so it is never readable by other local users,
        # not even for the instant between create and chmod.
        _atomic_write_secret(
            path, json.dumps(_to_dict(self), indent=2, ensure_ascii=False)
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


def import_owcfg(
    warpcfg_path: Path, dest: Path | None = None, *, enroll: bool = True
) -> ClientConfig:
    config, _verdict = import_owcfg_with_verdict(warpcfg_path, dest, enroll=enroll)
    return config


def import_owcfg_with_verdict(
    warpcfg_path: Path, dest: Path | None = None, *, enroll: bool = True
) -> tuple[ClientConfig, profile_trust.TrustVerdict]:
    try:
        text = warpcfg_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {warpcfg_path}") from exc
    return import_owcfg_text_with_verdict(text, dest, enroll=enroll)


def import_owcfg_text(
    text: str, dest: Path | None = None, *, enroll: bool = True
) -> ClientConfig:
    config, _verdict = import_owcfg_text_with_verdict(text, dest, enroll=enroll)
    return config


def import_owcfg_text_with_verdict(
    text: str, dest: Path | None = None, *, enroll: bool = True
) -> tuple[ClientConfig, profile_trust.TrustVerdict]:
    """Like import_owcfg_text but also returns the signature verdict.

    Verifies the profile's embedded signature (CONCEPTO-C prop.2) before
    parsing it into a ClientConfig — the raw dict is what the signature was
    computed over, so verification has to happen here rather than after
    _parse() has normalised it into the dataclass schema (defaults filled in,
    fields reordered) and lost byte-for-byte fidelity with what was signed.

    The verdict used to only reach a log line, so an unsigned profile or a
    rotated signing key looked like an ordinary import from every surface
    (CLI, GUI, TUI). Split into its own function rather than changing
    import_owcfg_text's return shape so the many existing callers/tests that
    only want the config are unaffected.
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Not valid JSON: {exc}") from exc

    from outwarp import profile_trust
    try:
        verdict = profile_trust.verify_and_pin(raw)
    except profile_trust.ProfileTrustError as exc:
        raise ConfigError(str(exc)) from exc

    return _finish_import(_parse(raw), dest, enroll), verdict


def _finish_import(config: ClientConfig, dest: Path | None, enroll: bool) -> ClientConfig:
    """Redeem an enrolment token if the profile has one, then persist.

    Enrolment lives behind the import functions rather than in each caller (GUI
    bridge, CLI, TUI modal) so no import path can accidentally skip it and write
    out a profile with no private key. ``enroll=False`` is for tests and for
    inspecting a profile without touching the network.

    The import is a network call in this case, which is why the module-level
    imports stay clean: outwarp.enroll depends on this module.
    """
    target = dest or default_config_path()
    if enroll:
        from outwarp.enroll import EnrollError, needs_enrollment
        from outwarp.enroll import enroll as _redeem
        if needs_enrollment(config):
            try:
                config = _redeem(config)
            except EnrollError as exc:
                # Every import surface handles ConfigError; an EnrollError
                # escaping here was a raw traceback in the CLI and a crash in
                # the TUI modal / GUI bridge.
                raise ConfigError(
                    f"{exc}\n"
                    "This profile must be enrolled against the server before "
                    "first use. Enrolment goes through the tunnel port itself, "
                    "so if the server is reachable the admin should check that "
                    "its enrolment listener is running (`outwarp-server doctor`), "
                    "or issue the profile with `outwarp-server add-client --embed-key`."
                ) from exc
    config.save(target)
    # Snapshot the untouched import so profile editing can always be undone.
    config.save(original_config_path(target))
    return config


# --- internal helpers ---

def _atomic_write_secret(path: Path, payload: str) -> None:
    """Atomically write ``payload`` to ``path`` with 0o600 permissions.

    ``tempfile.mkstemp`` opens the file with mode 0o600 on POSIX, and
    ``os.replace`` renames atomically on the same filesystem. The result: a
    reader either sees the old contents or the new ones, never a partial write
    at the process umask (typically 0o644, world-readable). Mirrors the
    server-side helper in outwarp_server.config.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


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
    if not isinstance(version, int) or version < 1:
        raise ConfigError(f"schema_version must be a positive integer, got {version!r}")
    if version > _SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version {version} (this client understands up to "
            f"{_SCHEMA_VERSION}). Update OutWarp client to a newer version."
        )

    enrollment = _parse_enrollment(raw.get("enrollment", {}))
    server = _parse_server(_require(raw, "server", "root"))
    tls = _parse_tls(_require(raw, "tls", "root"))
    tunnel = _parse_tunnel(_require(raw, "tunnel", "root"))
    wireguard = _parse_wireguard(
        _require(raw, "wireguard", "root"), enrolling=bool(enrollment.token)
    )
    routing = _parse_routing(_require(raw, "routing", "root"))
    reconnect = _parse_reconnect(raw.get("reconnect", {}))
    network = _parse_network(raw.get("network", {}))
    fallback = _parse_fallback(raw.get("fallback", {}))

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
        network=network,
        fallback=fallback,
        enrollment=enrollment,
        name=str(raw.get("name", "")),
        expires_at=expires_at,
    )


def _parse_enrollment(d: Any) -> EnrollmentConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'enrollment' must be an object")
    token = str(d.get("token", ""))
    url = str(d.get("url", ""))
    remote_port = d.get("remote_port", 0)
    if not isinstance(remote_port, int) or isinstance(remote_port, bool) or remote_port < 0:
        raise ConfigError(
            f"enrollment.remote_port must be a non-negative integer, got {remote_port!r}"
        )
    if remote_port > 65535:
        raise ConfigError(f"enrollment.remote_port must be at most 65535, got {remote_port}")
    if token and not (url or remote_port):
        raise ConfigError(
            "enrollment.token is set but neither enrollment.remote_port nor "
            "enrollment.url says where to redeem it"
        )
    if url and not url.startswith(("https://", "http://")):
        raise ConfigError(f"enrollment.url must be an http(s) URL, got {url!r}")
    return EnrollmentConfig(token=token, url=url, remote_port=remote_port)


def _parse_server(d: Any) -> ServerConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'server' must be an object")
    endpoint = str(_require(d, "endpoint", "server"))
    if not _is_valid_host(endpoint):
        raise ConfigError(f"server.endpoint is not a valid hostname or IP: {endpoint!r}")
    port = _require(d, "port", "server")
    prefix = str(_require(d, "http_upgrade_path_prefix", "server"))
    if not _PATH_PREFIX_RE.match(prefix):
        raise ConfigError(
            "server.http_upgrade_path_prefix must be 1-128 characters of letters, "
            f"digits, '.', '_' or '-', got {prefix!r}"
        )
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
    verify = str(d.get("verify", "pin")).strip().lower()
    if verify not in _TLS_VERIFY_MODES:
        raise ConfigError(
            f"tls.verify must be one of {', '.join(_TLS_VERIFY_MODES)}, got {verify!r}"
        )

    spki = str(d.get("spki_sha256", ""))
    if spki and not _FINGERPRINT_RE.match(spki):
        raise ConfigError(
            f"tls.spki_sha256 must be a colon-separated SHA-256 hex string "
            f"(e.g. 'AB:CD:...'), got {spki!r}"
        )

    # A CA-mode profile has no pin to carry, so the fingerprint stops being
    # required — but if one is present it still has to be well-formed rather
    # than silently ignored.
    fp = str(d["cert_fingerprint_sha256"]) if "cert_fingerprint_sha256" in d else ""
    if verify == "pin" and not fp and not spki:
        raise ConfigError(
            "tls needs cert_fingerprint_sha256 or spki_sha256 when verify is 'pin'"
        )
    if fp and not _FINGERPRINT_RE.match(fp):
        raise ConfigError(
            f"tls.cert_fingerprint_sha256 must be a colon-separated SHA-256 hex string "
            f"(e.g. 'AB:CD:...'), got {fp!r}"
        )
    return TlsConfig(cert_fingerprint_sha256=fp, verify=verify, spki_sha256=spki)


def _parse_tunnel(d: Any) -> TunnelConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'tunnel' must be an object")
    local_port = _require(d, "local_port", "tunnel")
    remote_host = str(_require(d, "remote_host", "tunnel"))
    remote_port = _require(d, "remote_port", "tunnel")
    for name, val in (("local_port", local_port), ("remote_port", remote_port)):
        if not isinstance(val, int) or not (1 <= val <= 65535):
            raise ConfigError(f"tunnel.{name} must be an integer between 1 and 65535, got {val!r}")
    if not _is_valid_host(remote_host):
        raise ConfigError(f"tunnel.remote_host is not a valid hostname or IP: {remote_host!r}")
    return TunnelConfig(
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port,
    )


def _parse_wireguard(d: Any, *, enrolling: bool = False) -> WireguardConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'wireguard' must be an object")
    mtu_raw = d.get("mtu", 1380)
    try:
        mtu = int(mtu_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"wireguard.mtu must be an integer, got {mtu_raw!r}") from exc
    if not (576 <= mtu <= 1500):
        raise ConfigError(f"wireguard.mtu must be between 576 and 1500, got {mtu}")
    # A profile still awaiting enrolment has no private key yet — that is the
    # entire point of it. Once redeemed it is saved back with one, and then the
    # normal requirement applies again.
    private_key = (
        str(d.get("client_private_key", ""))
        if enrolling
        else str(_require(d, "client_private_key", "wireguard"))
    )
    if private_key and not _WG_KEY_RE.match(private_key):
        raise ConfigError("wireguard.client_private_key is not a valid WireGuard key")

    server_public_key = str(_require(d, "server_public_key", "wireguard"))
    if not _WG_KEY_RE.match(server_public_key):
        raise ConfigError("wireguard.server_public_key is not a valid WireGuard key")

    preshared_key = str(d.get("preshared_key", ""))
    if preshared_key and not _WG_KEY_RE.match(preshared_key):
        raise ConfigError("wireguard.preshared_key is not a valid WireGuard key")

    tunnel_name = str(_require(d, "tunnel_name", "wireguard"))
    if not _TUNNEL_NAME_RE.match(tunnel_name):
        raise ConfigError(
            "wireguard.tunnel_name must be 1-15 characters of letters, digits, "
            f"'_' or '-', got {tunnel_name!r}"
        )

    client_address = str(_require(d, "client_address", "wireguard"))
    try:
        ipaddress.ip_interface(client_address)
    except ValueError as exc:
        raise ConfigError(
            f"wireguard.client_address is not a valid IP/prefix: {client_address!r}"
        ) from exc

    return WireguardConfig(
        tunnel_name=tunnel_name,
        client_address=client_address,
        client_private_key=private_key,
        server_public_key=server_public_key,
        dns=_parse_ip_list(d.get("dns", ["1.1.1.1"]), "wireguard.dns", allow_cidr=False),
        mtu=mtu,
        preshared_key=preshared_key,
    )


def _parse_routing(d: Any) -> RoutingConfig:
    if not isinstance(d, dict):
        raise ConfigError("Section 'routing' must be an object")
    bypass = _require(d, "bypass_ips", "routing")
    return RoutingConfig(bypass_ips=_parse_endpoint_list(bypass, "routing.bypass_ips"))


_HOSTILE_MODES = ("auto", "on", "off")


def _parse_network(d: Any) -> NetworkConfig:
    if not isinstance(d, dict):
        return NetworkConfig()
    raw_mode = d.get("hostile_mode", "auto")
    if not isinstance(raw_mode, str):
        raise ConfigError("network.hostile_mode must be a string")
    mode = raw_mode.strip().lower()
    if mode not in _HOSTILE_MODES:
        raise ConfigError(
            f"network.hostile_mode must be one of {_HOSTILE_MODES}, got '{raw_mode}'"
        )
    return NetworkConfig(hostile_mode=mode)


_PIN_MODES = ("pin", "tolerate", "none")
_SCHEMES = ("wss", "ws")


def _parse_fallback(d: Any) -> FallbackConfig:
    if not isinstance(d, dict):
        return FallbackConfig()
    enabled = bool(d.get("enabled", True))
    raw_list = d.get("strategies", [])
    if not isinstance(raw_list, list):
        raise ConfigError("fallback.strategies must be a list of strategy objects")
    strategies: list[StrategyConfig] = []
    seen_ids: set[str] = set()
    for entry in raw_list:
        if not isinstance(entry, dict):
            raise ConfigError("each fallback.strategies entry must be an object")
        sid = str(entry.get("id", "")).strip()
        if not sid:
            raise ConfigError("fallback strategy is missing a non-empty 'id'")
        if sid in seen_ids:
            raise ConfigError(f"duplicate fallback strategy id '{sid}'")
        seen_ids.add(sid)
        port = entry.get("port", 0)
        if not isinstance(port, int) or not (port == 0 or 1 <= port <= 65535):
            raise ConfigError(f"fallback strategy '{sid}' port must be 0 or 1-65535, got {port!r}")
        scheme = str(entry.get("scheme", "wss")).strip().lower() or "wss"
        if scheme not in _SCHEMES:
            raise ConfigError(f"fallback strategy '{sid}' scheme must be one of {_SCHEMES}")
        pin_mode = str(entry.get("pin_mode", "pin")).strip().lower() or "pin"
        if pin_mode not in _PIN_MODES:
            raise ConfigError(f"fallback strategy '{sid}' pin_mode must be one of {_PIN_MODES}")
        bypass_raw = entry.get("bypass_ips", [])
        if not isinstance(bypass_raw, list) or not all(isinstance(x, str) for x in bypass_raw):
            raise ConfigError(f"fallback strategy '{sid}' bypass_ips must be a list of strings")

        endpoint = str(entry.get("endpoint", ""))
        if endpoint and not _is_valid_host(endpoint):
            raise ConfigError(
                f"fallback strategy '{sid}' endpoint is not a valid hostname or IP: {endpoint!r}"
            )
        path_prefix = str(entry.get("path_prefix", ""))
        if path_prefix and not _PATH_PREFIX_RE.match(path_prefix):
            raise ConfigError(f"fallback strategy '{sid}' path_prefix is not a valid path segment")
        # sni_override, host_header, user_agent and proxy are free text passed
        # straight to wstunnel as CLI args / HTTP header values — no shape to
        # enforce beyond "can't smuggle a second header or argument in".
        for field_name, field_value in (
            ("sni_override", entry.get("sni_override", "")),
            ("host_header", entry.get("host_header", "")),
            ("user_agent", entry.get("user_agent", "")),
            ("proxy", entry.get("proxy", "")),
        ):
            if _has_control_chars(str(field_value)):
                raise ConfigError(
                    f"fallback strategy '{sid}' {field_name} contains a control character"
                )

        strategies.append(
            StrategyConfig(
                id=sid,
                endpoint=endpoint,
                port=port,
                scheme=scheme,
                sni_override=str(entry.get("sni_override", "")),
                host_header=str(entry.get("host_header", "")),
                user_agent=str(entry.get("user_agent", "")),
                path_prefix=path_prefix,
                proxy=str(entry.get("proxy", "")),
                pin_mode=pin_mode,
                force_hostile=bool(entry.get("force_hostile", False)),
                bypass_ips=tuple(bypass_raw),
            )
        )
    return FallbackConfig(enabled=enabled, strategies=tuple(strategies))


def _parse_reconnect(d: Any) -> ReconnectConfig:
    if not isinstance(d, dict):
        return ReconnectConfig()
    raw_max = d.get("max_attempts", 5)
    try:
        max_attempts = int(raw_max)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"reconnect.max_attempts must be an integer, got {raw_max!r}") from exc
    if max_attempts < 1:
        # max_attempts=0 would make TunnelManager fail before the first connect
        # attempt (0 >= 0), so the user sees an instant failure with no error.
        raise ConfigError(f"reconnect.max_attempts must be >= 1, got {max_attempts}")
    delays_raw = d.get("delays_seconds", [5, 10, 20, 30, 60])
    if not isinstance(delays_raw, list):
        raise ConfigError("reconnect.delays_seconds must be a list of integers")
    try:
        delays = [int(v) for v in delays_raw]
    except (TypeError, ValueError) as exc:
        # A string slips straight through to Event.wait() as a TypeError later;
        # reject it here where we can give a useful message.
        raise ConfigError(f"reconnect.delays_seconds must be a list of integers: {exc}") from exc
    if any(v < 1 for v in delays):
        raise ConfigError("reconnect.delays_seconds entries must be positive")
    return ReconnectConfig(max_attempts=max_attempts, delays_seconds=delays)


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
            # Written even when empty: a profile saved mid-enrolment has to
            # round-trip back into the same "no key yet" state, not become an
            # invalid one.
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
        "network": {
            "hostile_mode": cfg.network.hostile_mode,
        },
    }
    # Emitted only when they diverge from the v1 defaults, so a round-tripped v1
    # profile stays byte-identical to what the server issued.
    if cfg.tls.verify != "pin":
        d["tls"]["verify"] = cfg.tls.verify
    if cfg.tls.spki_sha256:
        d["tls"]["spki_sha256"] = cfg.tls.spki_sha256
    if cfg.server.fallback_ports:
        d["server"]["fallback_ports"] = list(cfg.server.fallback_ports)
    if cfg.wireguard.preshared_key:
        d["wireguard"]["preshared_key"] = cfg.wireguard.preshared_key
    if cfg.fallback.strategies or not cfg.fallback.enabled:
        d["fallback"] = _fallback_to_dict(cfg.fallback)
    if cfg.enrollment.token or cfg.enrollment.url or cfg.enrollment.remote_port:
        d["enrollment"] = {"token": cfg.enrollment.token}
        if cfg.enrollment.remote_port:
            d["enrollment"]["remote_port"] = cfg.enrollment.remote_port
        if cfg.enrollment.url:
            d["enrollment"]["url"] = cfg.enrollment.url
    if cfg.expires_at:
        d["meta"] = {"expires_at": cfg.expires_at}
    return d


def _fallback_to_dict(fb: FallbackConfig) -> dict[str, Any]:
    out: dict[str, Any] = {"enabled": fb.enabled}
    strategies: list[dict[str, Any]] = []
    for s in fb.strategies:
        entry: dict[str, Any] = {"id": s.id}
        # Only emit fields that diverge from the inherit-from-primary defaults so
        # a round-trip stays compact and human-readable.
        if s.endpoint:
            entry["endpoint"] = s.endpoint
        if s.port:
            entry["port"] = s.port
        if s.scheme != "wss":
            entry["scheme"] = s.scheme
        if s.sni_override:
            entry["sni_override"] = s.sni_override
        if s.host_header:
            entry["host_header"] = s.host_header
        if s.user_agent:
            entry["user_agent"] = s.user_agent
        if s.path_prefix:
            entry["path_prefix"] = s.path_prefix
        if s.proxy:
            entry["proxy"] = s.proxy
        if s.pin_mode != "pin":
            entry["pin_mode"] = s.pin_mode
        if s.force_hostile:
            entry["force_hostile"] = True
        if s.bypass_ips:
            entry["bypass_ips"] = list(s.bypass_ips)
        strategies.append(entry)
    if strategies:
        out["strategies"] = strategies
    return out


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
    "hostile_mode",
)


def _split_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [tok for tok in re.split(r"[,\s]+", value.strip()) if tok]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    raise ConfigError("expected a list of values")


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
        except ValueError as exc:
            raise ConfigError(f"{label}: invalid address '{item}'") from exc
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
        raise ConfigError(f"{label}: invalid value '{item}' (use an IP, CIDR or domain)")
    return out


def apply_profile_patch(cfg: ClientConfig, patch: dict[str, Any]) -> ClientConfig:
    """Return a new ClientConfig with the user-editable fields in `patch` applied.

    Raises ConfigError with a human-readable (English) message on bad input so
    both the TUI and GUI editors can surface it directly. config.py is
    platform- and locale-agnostic; localisation, if ever needed, belongs in the
    presentation layer.
    """
    name = cfg.name
    wg_changes: dict[str, Any] = {}
    routing = cfg.routing
    rc_changes: dict[str, Any] = {}
    network = cfg.network

    if "name" in patch:
        n = str(patch["name"]).strip()
        if not n:
            raise ConfigError("Profile name cannot be empty")
        name = n

    if "mtu" in patch:
        try:
            mtu = int(patch["mtu"])
        except (TypeError, ValueError) as exc:
            raise ConfigError("MTU must be an integer") from exc
        if not (576 <= mtu <= 1500):
            raise ConfigError("MTU must be between 576 and 1500")
        wg_changes["mtu"] = mtu

    if "dns" in patch:
        wg_changes["dns"] = _parse_ip_list(patch["dns"], "DNS", allow_cidr=False)

    if "client_address" in patch:
        addr = str(patch["client_address"]).strip()
        try:
            ipaddress.ip_interface(addr)
        except ValueError as exc:
            raise ConfigError(
                f"Invalid client IP: '{addr}' (use the form 10.0.0.2/32)"
            ) from exc
        wg_changes["client_address"] = addr

    if "bypass_ips" in patch:
        routing = replace(
            routing,
            bypass_ips=_parse_endpoint_list(patch["bypass_ips"], "Bypass routes"),
        )

    if "reconnect_max_attempts" in patch:
        try:
            ma = int(patch["reconnect_max_attempts"])
        except (TypeError, ValueError) as exc:
            raise ConfigError("Reconnect attempts must be an integer") from exc
        if not (1 <= ma <= 100):
            raise ConfigError("Reconnect attempts must be between 1 and 100")
        rc_changes["max_attempts"] = ma

    if "reconnect_delays" in patch:
        tokens = _split_list(patch["reconnect_delays"])
        if not tokens:
            raise ConfigError("Provide at least one reconnect delay")
        delays: list[int] = []
        for tok in tokens:
            try:
                v = int(tok)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"Invalid reconnect delay: '{tok}'") from exc
            if v < 1:
                raise ConfigError("Reconnect delays must be positive")
            delays.append(v)
        rc_changes["delays_seconds"] = delays

    if "hostile_mode" in patch:
        raw_h = patch["hostile_mode"]
        if not isinstance(raw_h, str):
            raise ConfigError("hostile_mode must be auto / on / off")
        mode = raw_h.strip().lower() or "auto"
        if mode not in _HOSTILE_MODES:
            raise ConfigError(
                f"hostile_mode must be one of {_HOSTILE_MODES}, got '{raw_h}'"
            )
        network = replace(cfg.network, hostile_mode=mode)

    return replace(
        cfg,
        name=name,
        wireguard=replace(cfg.wireguard, **wg_changes) if wg_changes else cfg.wireguard,
        routing=routing,
        reconnect=replace(cfg.reconnect, **rc_changes) if rc_changes else cfg.reconnect,
        network=network,
    )
