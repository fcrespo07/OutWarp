"""The server's minisign parser must accept exactly what the client's does.

They are separate copies in separate distributions, so nothing but a test stops
them drifting — and a drift would mean a release that one half of OutWarp can
update from and the other cannot.
"""

from __future__ import annotations

import pytest

from outwarp_server.minisign import MinisignError, verify

RELEASE_KEY = (
    "untrusted comment: minisign public key 3E1FCD8BF652EC28\n"
    "RWQo7FL2i80fPrFtvv7gB5xJCqS/7KTSu+VkoLRdnaQyTnwXXuemHydR\n"
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


def test_accepts_a_signature_made_by_minisign_itself() -> None:
    verify(MESSAGE, SIGNATURE, RELEASE_KEY)


def test_rejects_a_tampered_manifest() -> None:
    with pytest.raises(MinisignError):
        verify(MESSAGE + b"0000  smuggled.exe\n", SIGNATURE, RELEASE_KEY)


def test_the_compiled_in_key_is_the_one_that_signed_it() -> None:
    from outwarp_server import updater
    verify(MESSAGE, SIGNATURE, updater._MINISIGN_PUBLIC_KEY)
