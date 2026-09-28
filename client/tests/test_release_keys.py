"""The trusted release keys: compiled in, committed as .pub files, and chosen
by key ID so a backup key can take over from a lost primary."""
from __future__ import annotations

from pathlib import Path

import pytest

from outwarp import updater
from outwarp.minisign import MinisignError, key_id_hex, parse_public_key, verify_any

_ROOT = Path(__file__).resolve().parents[2]
_PUB_FILES = ("outwarp-release.pub", "outwarp-release-backup.pub")


def _normalised(text: str) -> str:
    return "\n".join(line.strip() for line in text.strip().splitlines())


def test_committed_pub_files_match_the_compiled_keys() -> None:
    # Users verify downloads by hand with the .pub files; the updaters use the
    # compiled copies. They must be the same keys, in the same order.
    present = [f for f in _PUB_FILES if (_ROOT / f).exists()]
    assert present[:1] == ["outwarp-release.pub"]
    assert len(present) == len(updater._MINISIGN_PUBLIC_KEYS)
    for name, compiled in zip(present, updater._MINISIGN_PUBLIC_KEYS, strict=True):
        assert _normalised((_ROOT / name).read_text()) == _normalised(compiled), name


def test_key_ids_are_distinct() -> None:
    ids = [parse_public_key(k)[0] for k in updater._MINISIGN_PUBLIC_KEYS]
    assert len(set(ids)) == len(ids)


def test_builds_trust_the_primary_and_the_backup() -> None:
    # Guards against a careless edit dropping the backup: with a single key,
    # losing it strands every install again (what happened to 3E1FCD8BF652EC28).
    ids = [key_id_hex(parse_public_key(k)[0]) for k in updater._MINISIGN_PUBLIC_KEYS]
    assert ids == ["A2E04F7F69ABA94F", "C864B6A98619FAC9"]


def test_key_id_hex_matches_what_minisign_prints() -> None:
    key_id, _ = parse_public_key(
        "untrusted comment: minisign public key 3E1FCD8BF652EC28\n"
        "RWQo7FL2i80fPrFtvv7gB5xJCqS/7KTSu+VkoLRdnaQyTnwXXuemHydR\n"
    )
    assert key_id_hex(key_id) == "3E1FCD8BF652EC28"


class TestVerifyAny:
    RELEASE_KEY = (
        "untrusted comment: minisign public key 3E1FCD8BF652EC28\n"
        "RWQo7FL2i80fPrFtvv7gB5xJCqS/7KTSu+VkoLRdnaQyTnwXXuemHydR\n"
    )
    OTHER_KEY = (
        "untrusted comment: minisign public key 0000000000000001\n"
        "RWQBAAAAAAAAAIo1SaBtOFYg1+LvyCg9KLhlSDDqFlcA2zqN2sdIfFwo\n"
    )
    MESSAGE = b"deadbeef  fake-asset.whl\ncafebabe  other-asset.exe\n"
    SIGNATURE = (
        "untrusted comment: signature from minisign secret key\n"
        "RUQo7FL2i80fPkuGPo6f4hcp41eVLbxnoNpbqsW2+SBumD5JMdvjByKWpW8s6xLw7do9dSVbXp5o"
        "/CPIrqJSHbye/1YOfTNFLwk=\n"
        "trusted comment: OutWarp signature round-trip test\n"
        "55pk/kESbaENvkSQZuJnBO7DYg0g/SYM2vjP5EfWYUPIYpeR2BOPz9sIkhJOFvqmSrXqyDfFVtWj"
        "28LR0aibCQ==\n"
    )

    def test_picks_the_key_that_made_the_signature(self) -> None:
        # Order does not matter: the backup may sign while the primary is listed first.
        assert verify_any(self.MESSAGE, self.SIGNATURE, (self.OTHER_KEY, self.RELEASE_KEY)) \
            == "3E1FCD8BF652EC28"

    def test_refuses_a_key_it_does_not_trust(self) -> None:
        with pytest.raises(MinisignError, match="3E1FCD8BF652EC28.*does not trust"):
            verify_any(self.MESSAGE, self.SIGNATURE, (self.OTHER_KEY,))

    def test_a_trusted_key_still_has_to_verify(self) -> None:
        with pytest.raises(MinisignError):
            verify_any(self.MESSAGE + b"x", self.SIGNATURE, (self.RELEASE_KEY,))
