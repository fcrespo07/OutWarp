from __future__ import annotations

from pathlib import Path

from outwarp_server import updater

_ROOT = Path(__file__).resolve().parents[2]


def _normalised(text: str) -> str:
    return "\n".join(line.strip() for line in text.strip().splitlines())


def test_committed_pub_files_match_the_compiled_keys() -> None:
    # Mirror of client/tests/test_release_keys.py: both updaters trust the same
    # keys, and the .pub files users verify with are those keys.
    present = [f for f in ("outwarp-release.pub", "outwarp-release-backup.pub")
               if (_ROOT / f).exists()]
    assert len(present) == len(updater._MINISIGN_PUBLIC_KEYS)
    for name, compiled in zip(present, updater._MINISIGN_PUBLIC_KEYS, strict=True):
        assert _normalised((_ROOT / name).read_text()) == _normalised(compiled), name
