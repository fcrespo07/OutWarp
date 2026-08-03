"""minisign signature verification for the update channel.

``SHA256SUMS.txt`` proves a download arrived intact. It does not prove who
published it: the manifest ships in the same GitHub release as the binary and
travels the same trust path, so whoever can publish a release can publish a
matching manifest. Signing the manifest with a key that lives *off* the release
infrastructure is what turns integrity into authenticity — and the public half
is compiled into the client, never fetched, or the problem would just move one
level up.

Ed25519 verification is implemented here rather than pulled from
``cryptography`` because the client deliberately has no compiled dependencies:
adding one would put a native wheel into every PyInstaller bundle to check one
signature. This is the RFC 8032 §6 reference implementation, verification only —
it touches no secret material, so the constant-time properties a signing
implementation would need do not apply.
"""

from __future__ import annotations

import base64
import hashlib
import logging

log = logging.getLogger(__name__)

# ── Ed25519 (RFC 8032 §6 reference, verify half) ─────────────────────────────

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493


def _modp_inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _modp_inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512_modq(s: bytes) -> int:
    return int.from_bytes(hashlib.sha512(s).digest(), "little") % _Q


def _point_add(P: tuple, Q: tuple) -> tuple:
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _P
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C = 2 * P[3] * Q[3] * _D % _P
    D = 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _point_mul(s: int, P: tuple) -> tuple:
    Q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P: tuple, Q: tuple) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % _P != 0:
        return False
    return (P[1] * Q[2] - Q[1] * P[2]) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _modp_inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_G_Y = 4 * _modp_inv(5) % _P
_G_X = _recover_x(_G_Y, 0)
_G = (_G_X, _G_Y, 1, _G_X * _G_Y % _P)


def _point_decompress(s: bytes) -> tuple | None:
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    A = _point_decompress(public_key)
    if A is None:
        return False
    Rs = signature[:32]
    R = _point_decompress(Rs)
    if R is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(Rs + public_key + message)
    return _point_equal(_point_mul(s, _G), _point_add(R, _point_mul(h, A)))


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
