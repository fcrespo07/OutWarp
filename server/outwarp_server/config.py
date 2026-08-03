from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_APP_NAME = "OutWarp"
_SCHEMA_VERSION = 1


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClientEntry:
    name: str
    public_key: str
    address: str
    # Per-peer WireGuard preshared key (base64). Empty for clients registered
    # before PSK support — those keep working without one.
    psk: str = ""
    # ISO-8601 date (YYYY-MM-DD) after which this client should be considered
    # expired. Empty = never expires. The server doesn't auto-revoke; the
    # `prune-expired` command and the client (which refuses an expired .owcfg)
    # enforce it.
    expires_at: str = ""


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
    # Port the enrolment listener binds. Behind Caddy it is loopback-only and
    # published on the public port under the secret path prefix; in the
    # self-signed branch it is a public HTTPS port of its own, using the same
    # certificate (and therefore the same pin) as the transport.
    enroll_port: int = 8444
    clients: list[ClientEntry] = field(default_factory=list)

    @property
    def behind_reverse_proxy(self) -> bool:
        return self.tls_mode == "acme"

    @property
    def enroll_path(self) -> str:
        """Public path of the enrolment endpoint in the Caddy-fronted branch.

        Derived from the same secret prefix as the transport so the endpoint is
        no more discoverable than the tunnel itself.
        """
        return f"/{self.http_upgrade_path_prefix.strip('/')}-enroll"

    @property
    def enroll_url(self) -> str:
        """Where a client posts its public key to redeem an enrolment token."""
        if self.behind_reverse_proxy:
            host = self.endpoint if self.port == 443 else f"{self.endpoint}:{self.port}"
            return f"https://{host}{self.enroll_path}"
        return f"https://{self.endpoint}:{self.enroll_port}/enroll"

    @classmethod
    def load(cls, path: Path) -> ServerConfig:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}") from exc
        return _parse(raw)

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


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(r"C:\ProgramData")
    else:
        base = Path("/etc")
    return base / "outwarp"


def default_config_path() -> Path:
    return default_config_dir() / "server_config.json"


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

    clients_raw = raw.get("clients", [])
    if not isinstance(clients_raw, list):
        raise ConfigError("clients must be a list")
    clients = [
        ClientEntry(
            name=str(_require(c, "name", "clients[]")),
            public_key=str(_require(c, "public_key", "clients[]")),
            address=str(_require(c, "address", "clients[]")),
            psk=str(c.get("psk", "")),
            expires_at=str(c.get("expires_at", "")),
        )
        for c in clients_raw
    ]

    return ServerConfig(
        schema_version=version,
        endpoint=str(_require(raw, "endpoint", "root")),
        port=port,
        http_upgrade_path_prefix=str(_require(raw, "http_upgrade_path_prefix", "root")),
        cert_path=str(_require(raw, "cert_path", "root")),
        key_path=str(_require(raw, "key_path", "root")),
        cert_fingerprint_sha256=str(_require(raw, "cert_fingerprint_sha256", "root")),
        spki_sha256=str(raw.get("spki_sha256", "")),
        tls_mode=tls_mode,
        internal_ws_port=internal_ws_port,
        acme_email=str(raw.get("acme_email", "")),
        enroll_port=enroll_port,
        wg_private_key=str(_require(raw, "wg_private_key", "root")),
        wg_public_key=str(_require(raw, "wg_public_key", "root")),
        subnet=str(_require(raw, "subnet", "root")),
        server_address=str(_require(raw, "server_address", "root")),
        wg_listen_port=wg_listen_port,
        clients=clients,
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
        "clients": [
            {
                "name": c.name,
                "public_key": c.public_key,
                "address": c.address,
                **({"psk": c.psk} if c.psk else {}),
                **({"expires_at": c.expires_at} if c.expires_at else {}),
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
