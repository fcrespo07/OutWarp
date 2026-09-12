from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

_APP_NAME = "OutWarp"
_SCHEMA_VERSION = 1


class ConfigError(ValueError):
    pass


# A client name doubles as a config identifier and the <name>.owcfg filename
# written to the cwd. Without this an unsanitised name like '../x' or 'a/b'
# would escape the directory or fail mid-write. Allow a conservative charset
# only; reject path separators, traversal and control characters. Lives here
# (not server_manager.py) so _parse() below can enforce it too without a
# circular import — server_manager imports ClientEntry/ServerConfig from here.
_CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")

# A WireGuard base64 key/PSK is always 44 chars, the last one from a fixed
# small alphabet. Mirrors enroll_server.py:_WG_KEY_RE — keep the two in sync.
_WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")

_EXPIRES_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# CONCEPTO-C prop.1 (OutWarp-fix-plan.md): server_config.json is semi-trusted
# (admin-written, 0o600, not something an attacker typically controls) but
# still gets the same baseline as the fully hostile .owcfg — cheap defense in
# depth, and it forces a decision every time a new field is added instead of
# defaulting silently to "no validation". `endpoint` and `http_upgrade_path_prefix`
# used to reach a Caddyfile / wstunnel argv untouched by a str(...) passthrough.
#
# RFC 1123 hostname: 1-63-char labels joined by dots, 253 chars total. Also
# used by caddy.py, which imports it from here rather than keeping its own
# copy (FIX-13a originally defined it there, for the Caddyfile domain).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
# Not full RFC 5322 — just enough to reject anything that could break out of
# a Caddyfile `email` directive or an ACME registration request.
_EMAIL_RE = re.compile(r"^[^\s{}\"']+@[^\s{}\"']+\.[^\s{}\"']+$")
# The wstunnel upgrade path prefix ends up as one argv element
# (--restrict-http-upgrade-path-prefix) and a Caddyfile path matcher — no
# slashes, spaces or control characters.
_PATH_PREFIX_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _is_valid_host(value: str) -> bool:
    """Whether `value` is shaped like an IP address or an RFC 1123 hostname."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(value))


def validate_client_name(name: str) -> str:
    """Return the stripped name if it is a safe identifier, else raise ValueError."""
    if not isinstance(name, str):
        raise ValueError("Client name must be text")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Client name is required")
    if cleaned in (".", ".."):
        raise ValueError("Invalid client name")
    if not _CLIENT_NAME_RE.match(cleaned):
        raise ValueError(
            "Client name may only contain letters, digits, spaces, '.', '_' and "
            "'-' (1-64 characters, not starting with a separator)"
        )
    return cleaned


_CLIENT_STATES = ("active", "revoked")


@dataclass(frozen=True)
class ClientEntry:
    name: str
    public_key: str
    address: str
    # Per-peer WireGuard preshared key (base64). Empty for clients registered
    # before PSK support — those keep working without one.
    psk: str = ""
    # ISO-8601 date (YYYY-MM-DD) after which this client should be considered
    # expired. wireguard.py's wg-conf builders exclude an expired client from
    # the live interface on the next regeneration (CONCEPTO-D) in addition to
    # the `prune-expired` command and the client's own refusal to import an
    # expired .owcfg.
    expires_at: str = ""
    # 'active' | 'revoked'. Revoking sets this rather than deleting the row
    # (client_store.py) — so "never enrolled" and "enrolled, then revoked"
    # stay distinguishable (CONCEPTO-D). Default 'active' so every existing
    # keyword-constructed ClientEntry(...) in the codebase and tests keeps
    # meaning what it always has.
    state: str = "active"
    # ISO-8601 date the public_key first became non-empty. Empty for a
    # reservation still awaiting enrolment, and for clients migrated from a
    # pre-CONCEPTO-A JSON config — that history genuinely isn't known.
    enrolled_at: str = ""


@dataclass(frozen=True)
class ServerConfig:
    schema_version: int
    endpoint: str
    port: int
    http_upgrade_path_prefix: str
    cert_path: str
    key_path: str
    cert_fingerprint_sha256: str
    wg_private_key: str
    wg_public_key: str
    subnet: str
    server_address: str
    wg_listen_port: int
    # SHA-256 of the TLS certificate's DER SubjectPublicKeyInfo. Clients pin this
    # in preference to cert_fingerprint_sha256 because it survives `renew-cert`.
    # Empty on configs written before the field existed; add-client/rotate-client
    # backfill it from the certificate on disk the next time they run.
    spki_sha256: str = ""
    # "self-signed": wstunnel holds the public port with its own certificate and
    # clients pin it. "acme": Caddy holds the port with a real Let's Encrypt
    # certificate and proxies the secret path to wstunnel on
    # 127.0.0.1:internal_ws_port; clients validate against the system CA store
    # instead of pinning. The second is the only branch that survives a network
    # inspecting TLS, and the only one where wstunnel itself verifies anything.
    tls_mode: str = "self-signed"
    internal_ws_port: int = 8080
    acme_email: str = ""
    # Loopback port the enrolment listener binds (enroll_server.py). Never
    # public: clients reach it as a wstunnel TCP forward over the transport
    # port, so the only thing to keep free here is the port itself.
    enroll_port: int = 8444
    # This server's own minisign keypair, used to sign every .owcfg it issues
    # (CONCEPTO-C prop.2 — see build_owcfg's docstring). Unrelated to the
    # project-wide release-signing key in docs/RELEASE_SIGNING.md: each
    # self-hosted server has its own, generated lazily by add-client /
    # rotate-client the first time either runs after an upgrade (same pattern
    # as spki_sha256 above). Empty on configs from before the field existed.
    owcfg_signing_key_id: str = ""       # hex, 8 bytes
    owcfg_signing_private_key: str = ""  # base64, 32 raw bytes
    owcfg_signing_public_key: str = ""   # minisign two-line public-key text
    clients: list[ClientEntry] = field(default_factory=list)

    @property
    def behind_reverse_proxy(self) -> bool:
        return self.tls_mode == "acme"

    @classmethod
    def load(cls, path: Path) -> ServerConfig:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}") from exc
        parsed = _parse(raw)

        # CONCEPTO-A: the client registry's source of truth is clients.sqlite,
        # a sibling of this file — not the "clients" array just parsed above,
        # which _parse() still reads only so migrate_from_json() has something
        # to import the very first time a server sees this module. Deferred
        # import: client_store.py imports ClientEntry from this module.
        from outwarp_server.client_store import ClientStore
        store = ClientStore(path.parent / "clients.sqlite")
        store.migrate_from_json(parsed.clients)
        return replace(parsed, clients=store.list_active())

    def save(self, path: Path) -> None:
        """Persist the server config with 0o600 perms.

        The file embeds the server's WireGuard private key and the wstunnel
        path-prefix used as a soft scanner gate; both have to stay
        unreadable by other local users. The atomic mkstemp+replace pattern
        guarantees the file never exists half-written at 0o644.
        """
        _atomic_write_secret(
            path, json.dumps(_to_dict(self), indent=2, ensure_ascii=False)
        )


# Set by the CLI when --config-dir is given (and settable by a container
# image) so every component that resolves the config dir on its own —
# ServerManager, the GUI bridge, the panel, the enrolment listener — agrees
# with the command line. Without it a `--config-dir /data serve` process
# reloaded /etc/outwarp/server_config.json from add_client and failed.
CONFIG_DIR_ENV = "OUTWARP_CONFIG_DIR"


def default_config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(r"C:\ProgramData")
    else:
        base = Path("/etc")
    return base / "outwarp"


def default_config_path() -> Path:
    return default_config_dir() / "server_config.json"


@contextlib.contextmanager
def locked_config(path: Path):
    """Hold an exclusive, cross-process OS lock scoped to one server_config.json.

    FIX-04 bridge patch. `add_client`/`revoke_client`/`rotate_client`
    (operations.py) read-modify-write `clients` with no lock at all: two
    processes racing (the always-running daemon's web panel, and a separate
    `outwarp-server add-client` invocation) can both read the same client
    list, both allocate the same pool IP, and have the second save silently
    clobber the first's new peer. `ServerManager._lock` (a plain
    `threading.Lock`) already serializes same-process callers; this closes the
    cross-process gap the same way. Callers must reload the config from
    `path` *inside* this context — the whole point is to mutate the freshest
    on-disk state, not a snapshot taken before the lock was acquired.

    This is a stopgap, not a transaction: it serializes writers around a
    whole-file read-modify-write, it does not model `clients` as anything
    richer than "whatever list was last saved". CONCEPTO-A (a client registry
    in its own SQLite table, à la traffic_history.py) is the real fix.

    A sidecar `.server_config.json.lock` file is locked rather than the real
    config file, so a plain `open()`/read of it elsewhere is never blocked.
    """
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if sys.platform == "win32":
            import msvcrt
            with contextlib.suppress(OSError):
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --- internal helpers ---


def _require(data: dict[str, Any], key: str, section: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required field '{key}' in section '{section}'")
    return data[key]


def _parse(raw: dict[str, Any]) -> ServerConfig:
    version = raw.get("schema_version", 1)
    if version != _SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version {version!r} (expected {_SCHEMA_VERSION})"
        )

    port = _require(raw, "port", "root")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"port must be an integer between 1 and 65535, got {port!r}")

    wg_listen_port = _require(raw, "wg_listen_port", "root")
    if not isinstance(wg_listen_port, int) or not (1 <= wg_listen_port <= 65535):
        raise ConfigError(
            f"wg_listen_port must be an integer between 1 and 65535, got {wg_listen_port!r}"
        )

    tls_mode = str(raw.get("tls_mode", "self-signed"))
    if tls_mode not in ("self-signed", "acme"):
        raise ConfigError(
            f"tls_mode must be 'self-signed' or 'acme', got {tls_mode!r}"
        )

    internal_ws_port = raw.get("internal_ws_port", 8080)
    if not isinstance(internal_ws_port, int) or not (1 <= internal_ws_port <= 65535):
        raise ConfigError(
            f"internal_ws_port must be an integer between 1 and 65535, "
            f"got {internal_ws_port!r}"
        )

    enroll_port = raw.get("enroll_port", 8444)
    if not isinstance(enroll_port, int) or not (1 <= enroll_port <= 65535):
        raise ConfigError(
            f"enroll_port must be an integer between 1 and 65535, got {enroll_port!r}"
        )

    subnet = str(_require(raw, "subnet", "root"))
    try:
        ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise ConfigError(f"subnet is not a valid network: {subnet!r}") from exc

    server_address = str(_require(raw, "server_address", "root"))
    try:
        ipaddress.ip_interface(server_address)
    except ValueError as exc:
        raise ConfigError(
            f"server_address is not a valid IP/prefix: {server_address!r}"
        ) from exc

    endpoint = str(_require(raw, "endpoint", "root"))
    if not _is_valid_host(endpoint):
        raise ConfigError(f"endpoint is not a valid hostname or IP: {endpoint!r}")

    http_upgrade_path_prefix = str(_require(raw, "http_upgrade_path_prefix", "root"))
    if not _PATH_PREFIX_RE.match(http_upgrade_path_prefix):
        raise ConfigError(
            "http_upgrade_path_prefix must be 1-128 characters of letters, digits, "
            f"'.', '_' or '-', got {http_upgrade_path_prefix!r}"
        )

    acme_email = str(raw.get("acme_email", ""))
    if acme_email and not _EMAIL_RE.match(acme_email):
        raise ConfigError(f"acme_email is not a valid email address: {acme_email!r}")

    clients_raw = raw.get("clients", [])
    if not isinstance(clients_raw, list):
        raise ConfigError("clients must be a list")
    clients = [_parse_client_entry(c) for c in clients_raw]

    return ServerConfig(
        schema_version=version,
        endpoint=endpoint,
        port=port,
        http_upgrade_path_prefix=http_upgrade_path_prefix,
        cert_path=str(_require(raw, "cert_path", "root")),
        key_path=str(_require(raw, "key_path", "root")),
        cert_fingerprint_sha256=str(_require(raw, "cert_fingerprint_sha256", "root")),
        spki_sha256=str(raw.get("spki_sha256", "")),
        tls_mode=tls_mode,
        internal_ws_port=internal_ws_port,
        acme_email=acme_email,
        enroll_port=enroll_port,
        wg_private_key=str(_require(raw, "wg_private_key", "root")),
        wg_public_key=str(_require(raw, "wg_public_key", "root")),
        subnet=subnet,
        server_address=server_address,
        wg_listen_port=wg_listen_port,
        owcfg_signing_key_id=_parse_owcfg_signing_key_id(raw),
        owcfg_signing_private_key=str(raw.get("owcfg_signing_private_key", "")),
        owcfg_signing_public_key=str(raw.get("owcfg_signing_public_key", "")),
        clients=clients,
    )


_HEX8_RE = re.compile(r"^[0-9a-fA-F]{16}$")


def _parse_owcfg_signing_key_id(raw: dict[str, Any]) -> str:
    key_id = str(raw.get("owcfg_signing_key_id", ""))
    if key_id and not _HEX8_RE.match(key_id):
        raise ConfigError(f"owcfg_signing_key_id must be 16 hex chars, got {key_id!r}")
    return key_id


def _parse_client_entry(c: Any) -> ClientEntry:
    try:
        name = validate_client_name(str(_require(c, "name", "clients[]")))
    except ValueError as exc:
        raise ConfigError(f"clients[]: {exc}") from exc

    # A client awaiting enrolment is stored with public_key == "" until it
    # redeems its token (see wireguard.py:build_server_wg_conf, which skips
    # peers without one) — empty is a valid, meaningful state, not garbage.
    public_key = str(_require(c, "public_key", "clients[]"))
    if public_key and not _WG_KEY_RE.match(public_key):
        raise ConfigError(f"clients[{name!r}].public_key is not a valid WireGuard key")

    address = str(_require(c, "address", "clients[]"))
    try:
        ipaddress.ip_interface(address)
    except ValueError as exc:
        raise ConfigError(
            f"clients[{name!r}].address is not a valid IP/prefix: {address!r}"
        ) from exc

    psk = str(c.get("psk", ""))
    if psk and not _WG_KEY_RE.match(psk):
        raise ConfigError(f"clients[{name!r}].psk is not a valid WireGuard key")

    expires_at = str(c.get("expires_at", ""))
    if expires_at and not _EXPIRES_AT_RE.match(expires_at):
        raise ConfigError(
            f"clients[{name!r}].expires_at must be YYYY-MM-DD, got {expires_at!r}"
        )

    state = str(c.get("state", "active"))
    if state not in _CLIENT_STATES:
        raise ConfigError(f"clients[{name!r}].state must be one of {_CLIENT_STATES}, got {state!r}")

    enrolled_at = str(c.get("enrolled_at", ""))
    if enrolled_at and not _EXPIRES_AT_RE.match(enrolled_at):
        raise ConfigError(
            f"clients[{name!r}].enrolled_at must be YYYY-MM-DD, got {enrolled_at!r}"
        )

    return ClientEntry(
        name=name, public_key=public_key, address=address, psk=psk, expires_at=expires_at,
        state=state, enrolled_at=enrolled_at,
    )


def _to_dict(cfg: ServerConfig) -> dict[str, Any]:
    return {
        "schema_version": cfg.schema_version,
        "endpoint": cfg.endpoint,
        "port": cfg.port,
        "http_upgrade_path_prefix": cfg.http_upgrade_path_prefix,
        "cert_path": cfg.cert_path,
        "key_path": cfg.key_path,
        "cert_fingerprint_sha256": cfg.cert_fingerprint_sha256,
        "spki_sha256": cfg.spki_sha256,
        "tls_mode": cfg.tls_mode,
        "internal_ws_port": cfg.internal_ws_port,
        "acme_email": cfg.acme_email,
        "enroll_port": cfg.enroll_port,
        "wg_private_key": cfg.wg_private_key,
        "wg_public_key": cfg.wg_public_key,
        "subnet": cfg.subnet,
        "server_address": cfg.server_address,
        "wg_listen_port": cfg.wg_listen_port,
        "owcfg_signing_key_id": cfg.owcfg_signing_key_id,
        "owcfg_signing_private_key": cfg.owcfg_signing_private_key,
        "owcfg_signing_public_key": cfg.owcfg_signing_public_key,
        "clients": [
            {
                "name": c.name,
                "public_key": c.public_key,
                "address": c.address,
                **({"psk": c.psk} if c.psk else {}),
                **({"expires_at": c.expires_at} if c.expires_at else {}),
                **({"state": c.state} if c.state != "active" else {}),
                **({"enrolled_at": c.enrolled_at} if c.enrolled_at else {}),
            }
            for c in cfg.clients
        ],
    }


def _atomic_write_secret(path: Path, payload: str) -> None:
    """Atomically write ``payload`` to ``path`` with 0o600 permissions.

    ``tempfile.mkstemp`` opens the file with mode 0o600 on POSIX, and
    ``os.replace`` is atomic on the same filesystem (rename(2) on POSIX,
    ReplaceFile on Windows). The result: a reader either sees the old
    contents or the new contents, never a partial write at 0o644.
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
