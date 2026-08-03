from __future__ import annotations

import binascii

import pytest

from outwarp.minisign import MinisignError, ed25519_verify, parse_public_key, verify

# RFC 8032 §7.1 test vectors. The Ed25519 verifier is hand-written (the client
# has no compiled crypto dependency), so it is checked against the standard's
# own vectors rather than only against signatures we produced ourselves.
RFC_VECTORS = [
    (
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da08"
        "5ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18"
        "ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]

# A real minisign-format keypair and signature, generated offline with a
# standard Ed25519 implementation, so the container parsing is exercised against
# the actual on-disk format rather than something we invented.
PUB_KEY = (
    "untrusted comment: minisign public key 0E96ABF060984099\n"
    "RUQOlqvwYJhAmWt4JyEv2Xxt75wysIfZ32ktDAaFC2gRhALSBj63QJsJ\n"
)
SIGNED_MESSAGE = b"abc123  SHA256SUMS-like content\n"
SIGNATURE = (
    "untrusted comment: signature from minisign secret key\n"
    "RUQOlqvwYJhAmc5sFUpL7qop9p/MRRkn/B8b3kvkyJd6WvHi8Ls/NIEf2lFtuv1OnlSgnilOaNnU"
    "zkrlm3CZ+rkP4pPCi81wKAE=\n"
    "trusted comment: timestamp:1767225600\tfile:SHA256SUMS.txt\n"
    "3vuif0C3Dhn0OngT6XXxJFeO6kfOCzbLF7XWj9SoMHI2nN7zUxLoNm+PzfsvQDtC1IEeNS3iMMLj"
    "r/WI973ZDg==\n"
)


class TestEd25519:
    @pytest.mark.parametrize("pub,msg,sig", RFC_VECTORS)
    def test_accepts_rfc8032_vectors(self, pub: str, msg: str, sig: str) -> None:
        assert ed25519_verify(
            binascii.unhexlify(pub), binascii.unhexlify(msg), binascii.unhexlify(sig)
        )

    def test_rejects_a_tampered_message(self) -> None:
        pub, msg, sig = RFC_VECTORS[1]
        assert not ed25519_verify(
            binascii.unhexlify(pub), b"different", binascii.unhexlify(sig)
        )

    def test_rejects_a_signature_from_another_key(self) -> None:
        pub = binascii.unhexlify(RFC_VECTORS[0][0])
        _, msg, sig = RFC_VECTORS[1]
        assert not ed25519_verify(pub, binascii.unhexlify(msg), binascii.unhexlify(sig))

    @pytest.mark.parametrize("pub,sig", [(b"", b"\x00" * 64), (b"\x00" * 32, b"")])
    def test_rejects_malformed_input(self, pub: bytes, sig: bytes) -> None:
        assert not ed25519_verify(pub, b"msg", sig)

    def test_rejects_an_unreduced_scalar(self) -> None:
        # s >= L must be refused: accepting it would make signatures malleable.
        pub, msg, sig = RFC_VECTORS[1]
        bad = binascii.unhexlify(sig)[:32] + b"\xff" * 32
        assert not ed25519_verify(binascii.unhexlify(pub), binascii.unhexlify(msg), bad)


class TestPublicKeyParsing:
    def test_parses_a_key_file_with_its_comment(self) -> None:
        key_id, pub = parse_public_key(PUB_KEY)
        assert len(key_id) == 8
        assert len(pub) == 32

    def test_parses_a_bare_base64_key(self) -> None:
        bare = PUB_KEY.splitlines()[1]
        assert parse_public_key(bare) == parse_public_key(PUB_KEY)

    @pytest.mark.parametrize("bad", ["", "not base64!!", "aGVsbG8="])
    def test_rejects_a_non_key(self, bad: str) -> None:
        with pytest.raises(MinisignError):
            parse_public_key(bad)


class TestVerify:
    def test_accepts_a_genuine_signature(self) -> None:
        verify(SIGNED_MESSAGE, SIGNATURE, PUB_KEY)

    def test_rejects_a_modified_message(self) -> None:
        with pytest.raises(MinisignError, match="does not match"):
            verify(SIGNED_MESSAGE + b"tampered\n", SIGNATURE, PUB_KEY)

    def test_rejects_a_signature_from_a_different_key(self) -> None:
        """The key id check is what turns 'some valid signature' into 'a
        signature from the maintainer'."""
        other = (
            "untrusted comment: minisign public key\n"
            "RUQAAAAAAAAAAGt4JyEv2Xxt75wysIfZ32ktDAaFC2gRhALSBj63QJsJ\n"
        )
        with pytest.raises(MinisignError, match="different key"):
            verify(SIGNED_MESSAGE, SIGNATURE, other)

    def test_rejects_a_tampered_trusted_comment(self) -> None:
        # The global signature exists precisely to bind the comment; without
        # checking it an attacker could rewrite what an operator reads.
        tampered = SIGNATURE.replace(
            "trusted comment: timestamp:1767225600\tfile:SHA256SUMS.txt",
            "trusted comment: timestamp:1767225600\tfile:totally-different.txt",
        )
        with pytest.raises(MinisignError, match="trusted comment"):
            verify(SIGNED_MESSAGE, tampered, PUB_KEY)

    def test_rejects_a_truncated_signature_file(self) -> None:
        only_sig = "\n".join(SIGNATURE.splitlines()[:2]) + "\n"
        with pytest.raises(MinisignError, match="trusted comment block"):
            verify(SIGNED_MESSAGE, only_sig, PUB_KEY)

    def test_rejects_an_empty_signature_file(self) -> None:
        with pytest.raises(MinisignError, match="empty"):
            verify(SIGNED_MESSAGE, "", PUB_KEY)

    def test_rejects_a_corrupt_signature_line(self) -> None:
        broken = SIGNATURE.replace(SIGNATURE.splitlines()[1], "!!!not base64!!!")
        with pytest.raises(MinisignError):
            verify(SIGNED_MESSAGE, broken, PUB_KEY)


class TestProductionKey:
    """Regression guard against the container parser drifting away from the real
    tool. The material below was produced by `minisign 0.12` itself against the
    project's actual release key — a synthetic fixture cannot prove we stayed
    compatible with the thing that will sign every release."""

    # Same key that is compiled into outwarp/updater.py and committed as
    # outwarp-release.pub.
    RELEASE_KEY = (
        "untrusted comment: minisign public key 3E1FCD8BF652EC28\n"
        "RWQo7FL2i80fPrFtvv7gB5xJCqS/7KTSu+VkoLRdnaQyTnwXXuemHydR\n"
    )
    MESSAGE = b"deadbeef  fake-asset.whl\ncafebabe  other-asset.exe\n"
    # Note the "ED" prefix: minisign >= 0.11 prehashes with BLAKE2b by default,
    # so this also pins that we handle the prehashed variant and not just legacy.
    SIGNATURE = (
        "untrusted comment: signature from minisign secret key\n"
        "RUQo7FL2i80fPkuGPo6f4hcp41eVLbxnoNpbqsW2+SBumD5JMdvjByKWpW8s6xLw7do9dSVbXp5o"
        "/CPIrqJSHbye/1YOfTNFLwk=\n"
        "trusted comment: OutWarp signature round-trip test\n"
        "55pk/kESbaENvkSQZuJnBO7DYg0g/SYM2vjP5EfWYUPIYpeR2BOPz9sIkhJOFvqmSrXqyDfFVtWj"
        "28LR0aibCQ==\n"
    )

    def test_accepts_a_signature_made_by_minisign_itself(self) -> None:
        verify(self.MESSAGE, self.SIGNATURE, self.RELEASE_KEY)

    def test_rejects_a_tampered_manifest(self) -> None:
        with pytest.raises(MinisignError):
            verify(self.MESSAGE + b"0000  smuggled.exe\n", self.SIGNATURE, self.RELEASE_KEY)

    def test_the_compiled_in_key_is_the_one_that_signed_it(self) -> None:
        from outwarp import updater
        verify(self.MESSAGE, self.SIGNATURE, updater._MINISIGN_PUBLIC_KEY)
