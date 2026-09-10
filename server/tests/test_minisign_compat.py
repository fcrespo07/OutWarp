"""The server's minisign parser must accept exactly what the client's does.

They are separate copies in separate distributions, so nothing but a test stops
them drifting — and a drift would mean a release that one half of OutWarp can
update from and the other cannot.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from outwarp_server.minisign import MinisignError, verify

_HAS_MINISIGN = shutil.which("minisign") is not None

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


# --- signing (CONCEPTO-C prop.2): output must interoperate with real minisign,
# not just with our own verify() — a format bug that both our signer and our
# verifier agree on would pass every test above while still being rejected by
# the actual tool. (This is exactly how format_public_key's algorithm-tag bug
# was found: 'ED' verified fine against our own parser but real minisign 0.12
# refused it with "Unsupported signature algorithm" — real minisign always
# tags the *public key* container 'Ed', varying only the signature's tag.) ---

@pytest.mark.skipif(not _HAS_MINISIGN, reason="real minisign binary not installed")
def test_our_signature_verifies_with_the_real_minisign_binary(tmp_path) -> None:
    from outwarp_server import minisign as ms

    key_id, private_key, public_key = ms.generate_keypair()
    pub_text = ms.format_public_key(key_id, public_key)
    message = b'{"hello":"world"}'
    sig_text = ms.sign(message, key_id, private_key, trusted_comment="interop test")

    (tmp_path / "msg.txt").write_bytes(message)
    (tmp_path / "msg.txt").with_suffix(".txt.pub").write_text(pub_text)
    (tmp_path / "msg.txt.minisig").write_text(sig_text)

    result = subprocess.run(
        ["minisign", "-V", "-p", str(tmp_path / "msg.txt.pub"), "-m", str(tmp_path / "msg.txt")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified" in result.stdout.lower()
