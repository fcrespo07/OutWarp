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
    clients: list[ClientEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> ServerConfig:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ConfigError(f"Config file not found: {path}")
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {exc}")
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
