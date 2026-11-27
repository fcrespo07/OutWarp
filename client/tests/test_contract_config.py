"""Contract test: the .owcfg / config.json shape is frozen at 1.0.

``config.example.owcfg`` is the documented ``.owcfg`` format. Parsing it and
writing it back must keep producing the same keys and value types. Adding an
optional key is fine (update the expectation); renaming, removing or retyping
one is a breaking change after 1.0 (``feat!:`` -> 2.0, or ship a migration).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from outwarp import config

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SHAPE = {
    "meta": {"expires_at": "str"},
    "name": "str",
    "network": {"hostile_mode": "str"},
    "reconnect": {"delays_seconds": ["int"], "max_attempts": "int"},
    "routing": {"bypass_ips": ["str"]},
    "schema_version": "int",
    "server": {
        "endpoint": "str",
        "fallback_ports": ["int"],
        "http_upgrade_path_prefix": "str",
        "port": "int",
    },
    "tls": {"cert_fingerprint_sha256": "str"},
    "tunnel": {"local_port": "int", "remote_host": "str", "remote_port": "int"},
    "wireguard": {
        "client_address": "str",
        "client_private_key": "str",
        "dns": ["str"],
        "mtu": "int",
        "preshared_key": "str",
        "server_public_key": "str",
        "tunnel_name": "str",
    },
}


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


def _example() -> dict:
    raw = json.loads((ROOT / "config.example.owcfg").read_text())
    key = lambda b: base64.b64encode(bytes([b]) * 32).decode()  # noqa: E731
    raw["wireguard"].update(
        client_private_key=key(1), server_public_key=key(2), preshared_key=key(3)
    )
    return raw


def test_example_owcfg_round_trips_with_frozen_shape() -> None:
    cfg = config._parse(_example())
    assert _shape(config._to_dict(cfg)) == EXPECTED_SHAPE


def test_schema_version_is_frozen() -> None:
    assert config._SCHEMA_VERSION == 4
    assert json.loads((ROOT / "config.example.owcfg").read_text())["schema_version"] <= 4


def test_older_schema_versions_still_load() -> None:
    raw = _example()
    raw["schema_version"] = 1
    assert config._parse(raw).schema_version == 1
