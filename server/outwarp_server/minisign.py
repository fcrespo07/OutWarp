"""minisign signature verification for the update channel.

``SHA256SUMS.txt`` proves a download arrived intact. It does not prove who
published it: the manifest ships in the same GitHub release as the binary and
travels the same trust path, so whoever can publish a release can publish a
matching manifest. Signing the manifest with a key that lives *off* the release
infrastructure is what turns integrity into authenticity — and the public half
is compiled into the client, never fetched, or the problem would just move one
level up.

Verification uses ``cryptography``, which the server already depends on. The
container parsing below is a deliberate mirror of the client's
``outwarp/minisign.py``: the two packages ship separately, so a shared import
is not available, and they must not drift on the format.
"""

from __future__ import annotations

import base64
import hashlib
import logging

log = logging.getLogger(__name__)

def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Thin wrapper over ``cryptography``'s Ed25519.

    The client ships a hand-rolled RFC 8032 verifier because it has no compiled
    dependencies; the server already depends on ``cryptography`` for its X.509
    work, so it uses that instead. Everything below this line is deliberately
    identical to ``client/outwarp/minisign.py`` — the two must agree on the
    container format or a signature valid for one would be invalid for the other.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


# ── minisign container format ────────────────────────────────────────────────

_ALG_LEGACY = b"Ed"    # signature over the file itself
_ALG_PREHASHED = b"ED"  # signature over BLAKE2b-512 of the file


class MinisignError(ValueError):
    pass


def parse_public_key(text: str) -> tuple[bytes, bytes]:
    """Parse a minisign public key (with or without its comment line).

    Returns (key_id, public_key).
    """
    line = _last_base64_line(text)
    if line is None:
        raise MinisignError("public key is not in minisign format")
    try:
        blob = base64.b64decode(line, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise MinisignError("public key is not valid base64") from exc
    if len(blob) != 42 or blob[:2] not in (_ALG_LEGACY, _ALG_PREHASHED):
        raise MinisignError("public key is not an Ed25519 minisign key")
    return blob[2:10], blob[10:]


def verify(message: bytes, signature_text: str, public_key_text: str) -> None:
    """Raise MinisignError unless `signature_text` is a valid signature.

    Both the file signature and minisign's "global" signature (which binds the
    trusted comment to it) are checked: verifying only the former would let an
    attacker who cannot forge signatures still swap the human-readable comment
    an operator might rely on.
    """
    key_id, public_key = parse_public_key(public_key_text)

    lines = [ln.rstrip("\r") for ln in signature_text.splitlines()]
    body = [ln for ln in lines if ln and not ln.startswith(("untrusted comment:",))]
    if len(body) < 1:
        raise MinisignError("signature file is empty")

    try:
        sig_blob = base64.b64decode(body[0], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise MinisignError("signature line is not valid base64") from exc
    if len(sig_blob) != 74:
        raise MinisignError("signature has an unexpected length")

    alg, sig_key_id, sig = sig_blob[:2], sig_blob[2:10], sig_blob[10:]
    if alg not in (_ALG_LEGACY, _ALG_PREHASHED):
        raise MinisignError(f"unsupported signature algorithm {alg!r}")
    if sig_key_id != key_id:
        raise MinisignError(
            "signature was made with a different key than the one built into this client"
        )

    signed = hashlib.blake2b(message).digest() if alg == _ALG_PREHASHED else message
    if not ed25519_verify(public_key, signed, sig):
        raise MinisignError("signature does not match the file")

    trusted_line = next((ln for ln in body[1:] if ln.startswith("trusted comment:")), None)
    global_line = next(
        (ln for ln in body[1:] if not ln.startswith("trusted comment:")), None
    )
    if trusted_line is None or global_line is None:
        # minisign always writes both; their absence means a truncated or
        # hand-made file, which we do not accept as a valid signature.
        raise MinisignError("signature file is missing its trusted comment block")
    trusted = trusted_line.split("trusted comment:", 1)[1].lstrip()
    try:
        global_sig = base64.b64decode(global_line, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise MinisignError("global signature is not valid base64") from exc
    if not ed25519_verify(public_key, sig + trusted.encode("utf-8"), global_sig):
        raise MinisignError("trusted comment does not match its signature")


def _last_base64_line(text: str) -> str | None:
    for raw in reversed(text.splitlines()):
        line = raw.strip()
        if line and not line.startswith(("untrusted comment:", "trusted comment:")):
            return line
    return None


# ── signing (server-only: owcfg profile signing, CONCEPTO-C prop.2) ─────────
#
# This half has no counterpart in the client's outwarp/minisign.py, and no
# relation to the project's release-signing key in docs/RELEASE_SIGNING.md
# ("the signing key does not go into a GitHub secret" is a rule for that key
# specifically — a one-of-a-kind key an offline maintainer machine holds to
# vouch for OutWarp releases). This is a *different* keypair: every
# self-hosted OutWarp server generates its own, to vouch for the .owcfg
# profiles it issues to its own clients. It is generated and held by the
# running server process — the release key's offline constraint does not
# apply to it, and could not: nothing else could sign on a headless VPS's own
# behalf. It only protects a .owcfg against tampering *after* the server
# signed it (email, USB, a shared drive) — see build_owcfg's docstring for
# what it does not protect against.


def generate_keypair() -> tuple[bytes, bytes, bytes]:
    """Generate a fresh Ed25519 keypair + random 8-byte key_id.

    Returns (key_id, private_key_32_bytes, public_key_32_bytes) — the raw key
    material, not yet in minisign's on-disk container format.
    """
    import secrets

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw,
    )
    return secrets.token_bytes(8), private_bytes, public_bytes


def format_public_key(key_id: bytes, public_key: bytes) -> str:
    """Render a public key in minisign's two-line text format (parseable by
    both this module's and the client's ``parse_public_key``).

    The container's algorithm tag is always ``Ed`` here regardless of which
    variant later signs with this key — verified against real minisign 0.12's
    own -G output, which does the same. Only the *signature* blob's tag
    varies between legacy and prehashed (see ``sign``).
    """
    blob = _ALG_LEGACY + key_id + public_key
    b64 = base64.b64encode(blob).decode("ascii")
    return f"untrusted comment: OutWarp .owcfg signing key {key_id.hex().upper()}\n{b64}\n"


def sign(
    message: bytes, key_id: bytes, private_key: bytes, *, trusted_comment: str,
) -> str:
    """Produce a minisign signature text for `message`, verifiable by this
    module's / the client's ``verify()`` against the matching public key.

    Prehashed (BLAKE2b-512) variant, matching what current ``minisign -S``
    produces — the same one release signatures use.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    signer = Ed25519PrivateKey.from_private_bytes(private_key)
    raw_sig = signer.sign(hashlib.blake2b(message).digest())
    sig_blob = _ALG_PREHASHED + key_id + raw_sig
    global_sig = signer.sign(raw_sig + trusted_comment.encode("utf-8"))
    return (
        "untrusted comment: signature\n"
        f"{base64.b64encode(sig_blob).decode('ascii')}\n"
        f"trusted comment: {trusted_comment}\n"
        f"{base64.b64encode(global_sig).decode('ascii')}\n"
    )
