"""Several connection profiles, one active at a time.

Layout under the user config directory::

    profiles/<id>/config.json            the profile (holds its WireGuard key)
    profiles/<id>/config.original.json   as imported, for "reset to defaults"
    active_profile                       the active profile's id

`config.default_config_path()` resolves to the active profile's config.json,
so every surface (GUI, TUI, CLI, daemon) that loads "the config" loads the
active profile without knowing profiles exist. Settings, pinned server keys
(known_servers.json) and the DNS cache stay global: they are keyed by server,
not by profile.

Before 0.16 there was a single `config.json` next to settings.json;
`migrate_legacy()` moves it into a profile the first time anything asks for
the active profile. It is idempotent and safe to call from every process.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

log = logging.getLogger(__name__)

_APP_NAME = "OutWarp"
_ACTIVE_FILE = "active_profile"
_CONFIG = "config.json"
_ORIGINAL = "config.original.json"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class ProfileRef:
    id: str
    path: Path  # the profile's config.json


def app_config_dir() -> Path:
    return Path(user_config_dir(_APP_NAME))


def profiles_dir() -> Path:
    return app_config_dir() / "profiles"


def config_path(profile_id: str) -> Path:
    return profiles_dir() / profile_id / _CONFIG


def legacy_config_path() -> Path:
    return app_config_dir() / _CONFIG


def valid_id(profile_id: str) -> bool:
    return bool(_ID_RE.match(profile_id or ""))


def list_profiles() -> list[ProfileRef]:
    migrate_legacy()
    root = profiles_dir()
    if not root.is_dir():
        return []
    return [
        ProfileRef(d.name, d / _CONFIG)
        for d in sorted(root.iterdir())
        if d.is_dir() and valid_id(d.name) and (d / _CONFIG).exists()
    ]


def active_id() -> str | None:
    """The active profile, or None when none is imported. A missing or stale
    `active_profile` falls back to the first profile, so a deleted or
    hand-edited pointer never strands the user with profiles but "none"."""
    profiles = list_profiles()
    ids = [p.id for p in profiles]
    with contextlib.suppress(OSError):
        pointed = (app_config_dir() / _ACTIVE_FILE).read_text(encoding="utf-8").strip()
        if pointed in ids:
            return pointed
    return ids[0] if ids else None


def set_active(profile_id: str) -> None:
    if profile_id not in {p.id for p in list_profiles()}:
        raise ProfileError(f"no profile '{profile_id}'")
    _write_active(profile_id)


def _write_active(profile_id: str) -> None:
    path = app_config_dir() / _ACTIVE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(profile_id + "\n", encoding="utf-8")
    os.replace(tmp, path)


def remove(profile_id: str) -> str | None:
    """Delete a profile; returns the id that is active afterwards (or None)."""
    if profile_id not in {p.id for p in list_profiles()}:
        raise ProfileError(f"no profile '{profile_id}'")
    was_active = active_id() == profile_id
    shutil.rmtree(profiles_dir() / profile_id)
    remaining = [p.id for p in list_profiles()]
    if was_active:
        if remaining:
            _write_active(remaining[0])
        else:
            with contextlib.suppress(OSError):
                (app_config_dir() / _ACTIVE_FILE).unlink()
    return active_id()


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:32].strip("-")
    return s or "profile"


def target_for_import(name: str, endpoint: str, client_address: str) -> str:
    """The id an imported profile is stored under.

    Re-importing the profile of the same server and tunnel address (a
    re-issued or rotated .owcfg keeps the address) replaces it, whatever the
    user renamed it to; anything else gets a new id, so two servers that both
    call you "laptop" do not overwrite each other.
    """
    import json

    for ref in list_profiles():
        try:
            raw = json.loads(ref.path.read_text(encoding="utf-8"))
            same = (
                raw["server"]["endpoint"] == endpoint
                and raw["wireguard"]["client_address"] == client_address
            )
        except (OSError, ValueError, KeyError, TypeError):
            same = False
        if same:
            return ref.id
    base = slug(name or endpoint)
    taken = {p.id for p in list_profiles()}
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base[:36]}-{n}"
        n += 1
    return candidate


def migrate_legacy() -> None:
    """Move a pre-0.16 single `config.json` into `profiles/<id>/` and make it
    active. No-op when there is nothing to move or profiles already exist."""
    legacy = legacy_config_path()
    if not legacy.exists():
        return
    root = profiles_dir()
    if root.is_dir() and any((d / _CONFIG).exists() for d in root.iterdir() if d.is_dir()):
        return
    try:
        import json

        raw = json.loads(legacy.read_text(encoding="utf-8"))
        name = raw.get("name", "") or raw.get("server", {}).get("endpoint", "")
    except (OSError, ValueError, AttributeError):
        name = ""
    profile_id = slug(name)
    dest = root / profile_id
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(root, 0o700)
            os.chmod(dest, 0o700)
        original = legacy.with_name(_ORIGINAL)
        if original.exists():
            os.replace(original, dest / _ORIGINAL)
        os.replace(legacy, dest / _CONFIG)
        _write_active(profile_id)
        log.info("migrated the single-profile config to profiles/%s", profile_id)
    except OSError as exc:
        # Another process may have won the race; if not, the legacy file stays
        # where it was and default_config_path keeps using it.
        log.warning("could not migrate config.json to profiles/: %s", exc)
