from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp.settings import (
    default_settings,
    load_settings,
    save_settings,
)


def test_save_settings_is_atomic_via_replace(tmp_path: Path) -> None:
    """save_settings must write through a sibling temp file and os.replace it
    onto the target. A direct `write_text` would expose torn writes — a crash
    between truncate and full write would leave a 0-byte settings.json that
    load_settings silently replaces with the defaults, wiping user prefs."""
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"language": "en"}))  # something to overwrite

    captured = {}

    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        captured["src"] = src
        captured["dst"] = dst
        real_replace(src, dst)

    with patch("outwarp.settings.os.replace", side_effect=spy_replace):
        save_settings({"language": "es", "theme": "dark"}, target)

    # Confirm os.replace was used and pointed at a sibling temp, not target.
    # ``dst`` is the Path object we passed; ``src`` is the tempfile path string
    # mkstemp returned. Coerce both to str so the comparison is layout-agnostic.
    assert str(captured["dst"]) == str(target)
    assert str(captured["src"]) != str(target)
    assert Path(str(captured["src"])).parent == target.parent

    assert json.loads(target.read_text()) == {"language": "es", "theme": "dark"}


def test_save_settings_does_not_truncate_target_on_failure(tmp_path: Path) -> None:
    """A failed save (e.g. os.replace raises) must NOT leave the existing
    settings.json in a partial state. The previous content stays intact."""
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"language": "en", "theme": "light"}))
    original = target.read_text()

    with (
        patch("outwarp.settings.os.replace", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        save_settings({"language": "es"}, target)

    # Target untouched.
    assert target.read_text() == original
    # Temp file cleaned up — no .settings-*.json.tmp left behind.
    leftovers = list(target.parent.glob(".settings-*.json.tmp"))
    assert leftovers == [], f"leaked temp files: {leftovers}"


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    """The atomic-save rewrite mustn't break the load shape."""
    target = tmp_path / "settings.json"
    save_settings({"language": "es", "kill_switch": True}, target)

    loaded = load_settings(target)
    assert loaded["language"] == "es"
    assert loaded["kill_switch"] is True
    # Missing keys fall back to defaults.
    defaults = default_settings()
    for key, value in defaults.items():
        if key in ("language", "kill_switch"):
            continue
        assert loaded[key] == value


def test_load_settings_on_zero_byte_file_returns_defaults(tmp_path: Path) -> None:
    """If a previous (pre-atomic) version of this code left a torn 0-byte
    settings.json on disk, the next launch must still come up rather than
    crash — so the JSONDecodeError swallow stays. This documents the contract
    even though the new save path prevents the situation."""
    target = tmp_path / "settings.json"
    target.write_bytes(b"")
    assert load_settings(target) == default_settings()
