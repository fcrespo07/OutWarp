"""The server's minisign parser must accept exactly what the client's does.

They are separate copies in separate distributions, so nothing but a test stops
them drifting — and a drift would mean a release that one half of OutWarp can
update from and the other cannot.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from outwarp_server.minisign import MinisignError, verify, verify_any

_HAS_MINISIGN = shutil.which("minisign") is not None

# Same material as client/tests/test_minisign.py::TestProductionKey: made by
# minisign 0.12 with the real primary and backup release keys.
RELEASE_KEY = (
    "untrusted comment: minisign public key A2E04F7F69ABA94F\n"
    "RWRPqatpf0/goqisSdUajHgymIamOGelwrG4pPrTGBrNbG2RIz74vBZ/\n"
)
MESSAGE = b"deadbeef  fake-asset.whl\ncafebabe  other-asset.exe\n"
SIGNATURE = (
    "untrusted comment: signature from minisign secret key\n"
    "RURPqatpf0/gor/VxOLDQbMfs5G/e5cXwtJtxeUvllCmbEqmHMJjApJLf6Jzx2FNp2CFPwXsj3w963sc"
    "inJMRoaHC+sE0wzblgU=\n"
    "trusted comment: OutWarp signature round-trip test\n"
    "S07c/M+sMS4UKbNqCv2v/GfGiTIg4zNFjKO0VdWsmjjXcwlL27T9IK4o1K5FPs0mWsgQew2hNTiSDVk4"
    "8SXqBw==\n"
)
BACKUP_SIGNATURE = (
    "untrusted comment: signature from minisign secret key\n"
    "RUTJ+hmGqbZkyF9CkJW3Af33HkENZUArlIkibfvMtwFW8RA3VoAN5ixYpt1ZohvLjtf3hLpYGeDLJIPj"
    "AIQt/E/2XBph+kGxIQQ=\n"
    "trusted comment: OutWarp signature round-trip test\n"
    "8K8AdqUmffbnPQFCwQPHqxwkMw9v12VVYKHXsL7JNSmgAdhCVzVlA1BfFG2d5v2CBod9knpkmUx+GzMj"
    "D13CCA==\n"
)


def test_accepts_a_signature_made_by_minisign_itself() -> None:
    verify(MESSAGE, SIGNATURE, RELEASE_KEY)


def test_rejects_a_tampered_manifest() -> None:
    with pytest.raises(MinisignError):
        verify(MESSAGE + b"0000  smuggled.exe\n", SIGNATURE, RELEASE_KEY)


def test_the_compiled_in_keys_are_the_ones_that_signed_them() -> None:
    from outwarp_server import updater

    keys = updater._MINISIGN_PUBLIC_KEYS
    assert verify_any(MESSAGE, SIGNATURE, keys) == "A2E04F7F69ABA94F"
    assert verify_any(MESSAGE, BACKUP_SIGNATURE, keys) == "C864B6A98619FAC9"


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
