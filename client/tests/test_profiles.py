"""Several profiles, one active: storage, migration from the single-profile
layout, import identity and the active pointer."""
from __future__ import annotations

import copy
import json
import stat
import sys

import pytest

from outwarp import profiles
from outwarp.config import ClientConfig, default_config_path, import_owcfg_text

_OWCFG = {
    "version": 1,
    "name": "laptop",
    "server": {"endpoint": "203.0.113.42", "port": 443, "http_upgrade_path_prefix": "s3cr3t"},
    "tls": {"cert_fingerprint_sha256": ":".join(["AB"] * 32)},
    "tunnel": {"local_port": 51820, "remote_host": "10.0.0.1", "remote_port": 51820},
    "wireguard": {
        "tunnel_name": "OutWarp",
        "client_address": "10.0.0.2/32",
        "client_private_key": "YGb2S9CXgF1HOlNjUq0Kw+zg1d6hPn+7L3bGrmgf+H4=",
        "server_public_key": "arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA=",
        "dns": ["1.1.1.1"],
    },
    "routing": {"bypass_ips": ["203.0.113.42"]},
    "reconnect": {"max_attempts": 5, "delays_seconds": [5, 10, 20, 30, 60]},
}


def _owcfg(**changes: object) -> str:
    raw = copy.deepcopy(_OWCFG)
    for dotted, value in changes.items():
        node = raw
        *path, leaf = dotted.split("__")
        for key in path:
            node = node[key]
        node[leaf] = value
    return json.dumps(raw)


def _import(text: str) -> ClientConfig:
    return import_owcfg_text(text, enroll=False)


def test_nothing_imported() -> None:
    assert profiles.list_profiles() == []
    assert profiles.active_id() is None
    assert not default_config_path().exists()


def test_import_creates_an_active_profile() -> None:
    _import(_owcfg())
    assert profiles.active_id() == "laptop"
    assert default_config_path() == profiles.config_path("laptop")
    assert ClientConfig.load(default_config_path()).name == "laptop"
    assert (profiles.config_path("laptop").parent / "config.original.json").exists()


def test_a_second_server_adds_a_profile_and_becomes_active() -> None:
    _import(_owcfg())
    _import(_owcfg(name="laptop", server__endpoint="198.51.100.7"))
    assert [p.id for p in profiles.list_profiles()] == ["laptop", "laptop-2"]
    assert profiles.active_id() == "laptop-2"


def test_reimporting_the_same_profile_replaces_it_even_if_renamed() -> None:
    _import(_owcfg())
    edited = ClientConfig.load(default_config_path())
    from dataclasses import replace
    replace(edited, name="work laptop").save(default_config_path())
    _import(_owcfg(wireguard__client_private_key="kPBqhWmv8kR3OWb4cUE4MkxXoAHDk1WEVExI6tU3G2Y="))
    assert [p.id for p in profiles.list_profiles()] == ["laptop"]


def test_switch_and_remove() -> None:
    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    profiles.set_active("laptop")
    assert ClientConfig.load(default_config_path()).server.endpoint == "203.0.113.42"
    with pytest.raises(profiles.ProfileError):
        profiles.set_active("nope")
    # Removing the active one activates what is left.
    assert profiles.remove("laptop") == "work"
    assert profiles.remove("work") is None
    assert profiles.active_id() is None


def test_a_stale_pointer_falls_back_to_a_real_profile() -> None:
    _import(_owcfg())
    (profiles.app_config_dir() / "active_profile").write_text("deleted-one\n")
    assert profiles.active_id() == "laptop"


def test_migrates_the_single_profile_layout_once() -> None:
    root = profiles.app_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(_owcfg(name="Home VPN"))
    (root / "config.original.json").write_text(_owcfg(name="Home VPN"))
    (root / "settings.json").write_text('{"language": "es"}')

    assert profiles.active_id() == "home-vpn"
    moved = profiles.config_path("home-vpn")
    assert moved.exists() and moved.with_name("config.original.json").exists()
    assert not (root / "config.json").exists()
    # Settings stay global.
    assert (root / "settings.json").exists()
    # Idempotent: nothing left to move, nothing moves again.
    profiles.migrate_legacy()
    assert [p.id for p in profiles.list_profiles()] == ["home-vpn"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_profile_dirs_are_private() -> None:
    _import(_owcfg())
    for path in (profiles.profiles_dir(), profiles.config_path("laptop").parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE(profiles.config_path("laptop").stat().st_mode) == 0o600


@pytest.mark.parametrize(("text", "expected"), [
    ("Home VPN", "home-vpn"), ("", "profile"), ("ÑANDÚ!!", "nandu"), ("a" * 60, "a" * 32),
])
def test_slug(text: str, expected: str) -> None:
    assert profiles.slug(text) == expected


def test_settings_are_shared_by_every_profile() -> None:
    from outwarp.settings import load_settings, save_settings

    _import(_owcfg())
    save_settings({**load_settings(), "language": "es"})
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    assert load_settings()["language"] == "es"


# --- API -------------------------------------------------------------------

def _api():
    from outwarp.api import Api
    from outwarp.logs import MemoryLogHandler

    replaced: list = []
    api = Api(MemoryLogHandler(), None, on_manager_replaced=replaced.append)
    api._emit = lambda *a, **k: None
    return api, replaced


def test_api_lists_every_profile_and_flags_the_active_one() -> None:
    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    api, _ = _api()
    listed = {p["id"]: p for p in api.list_profiles()}
    assert set(listed) == {"laptop", "work"}
    assert listed["work"]["active"] and not listed["laptop"]["active"]
    assert "client_private_key" not in str(listed)


def test_api_switch_leaves_the_new_profile_disconnected() -> None:
    from unittest.mock import MagicMock

    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    api, replaced = _api()
    old = MagicMock()
    api._manager = old
    result = api.set_active_profile("laptop")
    assert result["ok"] and result["profile"]["id"] == "laptop"
    old.stop.assert_called_once()
    assert profiles.active_id() == "laptop"
    assert api._manager.config.server.endpoint == "203.0.113.42"
    assert replaced[-1] is api._manager
    assert api._manager.state.value == "disconnected"
    assert api.set_active_profile("nope")["ok"] is False


def test_api_remove_active_activates_the_next() -> None:
    from unittest.mock import MagicMock

    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    api, replaced = _api()
    api._manager = MagicMock()
    assert api.remove_profile("work") == {"ok": True, "active_profile_id": "laptop"}
    assert api._manager.config.name == "laptop"
    assert api.remove_profile("laptop") == {"ok": True, "active_profile_id": None}
    assert api._manager is None and replaced[-1] is None


def test_api_refuses_to_switch_under_the_background_service() -> None:
    _import(_owcfg())
    api, _ = _api()
    api._service_managed = True
    assert api.set_active_profile("laptop")["ok"] is False
    assert api.remove_profile("laptop")["ok"] is False


# --- CLI -------------------------------------------------------------------

def test_cli_profile_list_use_remove(capsys, monkeypatch) -> None:
    from outwarp import cli

    monkeypatch.setattr(cli, "_tunnel_in_use", lambda: None)
    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))

    assert cli.main(["profile", "list"]) == 0
    out = capsys.readouterr().out
    assert "* work" in out and "  laptop" in out

    assert cli.main(["profile", "use", "laptop"]) == 0
    assert profiles.active_id() == "laptop"
    assert cli.main(["profile", "use", "nope"]) == 1

    assert cli.main(["profile"]) == 0  # bare: details of the active profile
    assert "203.0.113.42" in capsys.readouterr().out

    assert cli.main(["profile", "remove", "laptop", "-y"]) == 0
    assert profiles.active_id() == "work"


def test_cli_will_not_switch_while_the_tunnel_is_up(capsys, monkeypatch) -> None:
    from outwarp import cli

    _import(_owcfg())
    _import(_owcfg(name="work", server__endpoint="198.51.100.7"))
    monkeypatch.setattr(cli, "_tunnel_in_use", lambda: "outwarp connect (pid 42)")
    assert cli.main(["profile", "use", "laptop"]) == 1
    assert "Disconnect it first" in capsys.readouterr().err
    assert profiles.active_id() == "work"
