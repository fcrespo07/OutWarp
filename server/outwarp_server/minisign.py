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
