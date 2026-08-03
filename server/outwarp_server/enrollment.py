"""One-time enrolment tokens, so client private keys never exist on the server.

Before this existed, ``add-client`` generated the client's WireGuard keypair here
and shipped the private half inside the .owcfg. That made every profile a
permanent, complete credential for its whole journey — Telegram, email, a USB
stick — and left a copy of every client's identity in the server's config
directory and in every backup of it.

The replacement keeps the "one file, import it, done" experience but changes what
the file carries. ``add-client --enroll`` reserves the client's slot (name, IP,
preshared key) and mints a single-use token with a short TTL. The client
generates its own keypair on import and posts only the *public* half to redeem
the token. The server never sees a client private key, and an intercepted .owcfg
is worth something only inside the TTL window — and burning it is loud, because
the legitimate client's redemption then fails with "already used" instead of
quietly succeeding for both.

Tokens are stored the way the web panel stores its admin token: salted scrypt
hash only, never the plaintext.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from outwarp_server.config import _atomic_write_secret
from outwarp_server.web_auth import hash_secret, scrypt_params

log = logging.getLogger(__name__)

TOKEN_PREFIX = "ow_enroll_"
DEFAULT_TTL_SECONDS = 15 * 60
# How long spent tokens stick around. Long enough that a client re-importing the
# same file gets "already used" rather than "unknown token", which is the
# difference between a clear message and a confusing one.
_RETENTION_SECONDS = 7 * 86400

_write_lock = threading.Lock()


class EnrollmentError(RuntimeError):
    """Base class. The HTTP layer maps every subclass to 403 — the distinction
    is for the human reading the message, not an access-control decision."""


class TokenUnknownError(EnrollmentError):
    pass


class TokenExpiredError(EnrollmentError):
    pass


class TokenAlreadyUsedError(EnrollmentError):
    pass


@dataclass(frozen=True)
class EnrollmentToken:
    client_name: str
    salt: str
    token_hash: str
    created_at: int
    expires_at: int
    used_at: int = 0
    scrypt: dict[str, int] | None = None

    @property
    def used(self) -> bool:
        return self.used_at > 0

    def expired(self, now: int | None = None) -> bool:
        return (now if now is not None else int(time.time())) >= self.expires_at

    def to_dict(self) -> dict:
        return {
            "client_name": self.client_name,
            "salt": self.salt,
            "token_hash": self.token_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "used_at": self.used_at,
            "scrypt": self.scrypt or scrypt_params(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> EnrollmentToken:
        return cls(
            client_name=str(raw["client_name"]),
            salt=str(raw["salt"]),
            token_hash=str(raw["token_hash"]),
            created_at=int(raw.get("created_at", 0)),
            expires_at=int(raw.get("expires_at", 0)),
            used_at=int(raw.get("used_at", 0)),
            scrypt=raw.get("scrypt") or None,
        )


def store_path(config_dir: Path) -> Path:
    return config_dir / "enrollment_tokens.json"


def load(config_dir: Path) -> list[EnrollmentToken]:
    path = store_path(config_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw.get("tokens", []) if isinstance(raw, dict) else []
    out: list[EnrollmentToken] = []
    for e in entries:
        try:
            out.append(EnrollmentToken.from_dict(e))
        except (KeyError, TypeError, ValueError):
            log.warning("Skipping malformed enrolment token entry")
    return out


def save(config_dir: Path, tokens: list[EnrollmentToken]) -> None:
    payload = json.dumps(
        {"version": 1, "tokens": [t.to_dict() for t in tokens]}, indent=2
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_secret(store_path(config_dir), payload)


def issue(
    config_dir: Path, client_name: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> str:
    """Mint a token for `client_name` and return the plaintext exactly once.

    Any unused token already outstanding for the same name is dropped, so
    re-running ``add-client --enroll`` after a lost .owcfg invalidates the old
    one instead of leaving two live credentials for one slot.
    """
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    now = int(time.time())
    entry = EnrollmentToken(
        client_name=client_name,
        salt=salt.hex(),
        token_hash=hash_secret(token, salt).hex(),
        created_at=now,
        expires_at=now + ttl_seconds,
        scrypt=scrypt_params(),
    )
    with _write_lock:
        kept = [
            t for t in load(config_dir)
            if not (t.client_name == client_name and not t.used)
        ]
        save(config_dir, [*_prune(kept, now), entry])
    return token


def redeem(config_dir: Path, token: str) -> EnrollmentToken:
    """Consume `token` and return its record, or raise an EnrollmentError.

    The used marker is written before the caller registers the peer, and under
    the same lock as the lookup, so two simultaneous redemptions of one token
    cannot both win.
    """
    if not token:
        raise TokenUnknownError("No enrolment token supplied")
    now = int(time.time())
    with _write_lock:
        tokens = load(config_dir)
        idx = _find(tokens, token)
        if idx is None:
            raise TokenUnknownError("Enrolment token is not recognised")
        entry = tokens[idx]
        if entry.used:
            raise TokenAlreadyUsedError(
                f"This enrolment token was already redeemed at "
                f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(entry.used_at))}. "
                "If that was not you, the profile was intercepted — revoke the "
                "client and issue a new one."
            )
        if entry.expired(now):
            raise TokenExpiredError(
                "Enrolment token has expired. Ask the server admin for a new profile."
            )
        redeemed = replace(entry, used_at=now)
        tokens[idx] = redeemed
        save(config_dir, _prune(tokens, now))
    return redeemed


def pending(config_dir: Path) -> list[EnrollmentToken]:
    """Tokens that are still redeemable — what `list-clients` shows as pending."""
    now = int(time.time())
    return [t for t in load(config_dir) if not t.used and not t.expired(now)]


def revoke(config_dir: Path, client_name: str) -> int:
    """Drop every outstanding token for `client_name`. Returns how many."""
    with _write_lock:
        tokens = load(config_dir)
        kept = [
            t for t in tokens
            if not (t.client_name == client_name and not t.used)
        ]
        removed = len(tokens) - len(kept)
        if removed:
            save(config_dir, kept)
    return removed


def _find(tokens: list[EnrollmentToken], token: str) -> int | None:
    """Locate `token` by comparing against every stored hash.

    Every candidate is hashed even after a match is found: bailing early would
    make the response time depend on the token's position in the file, which is
    a (weak, but free to avoid) oracle. `secrets.compare_digest` handles the
    comparison itself.
    """
    found: int | None = None
    for i, entry in enumerate(tokens):
        try:
            salt = bytes.fromhex(entry.salt)
            expected = bytes.fromhex(entry.token_hash)
            params = entry.scrypt or scrypt_params()
            digest = hash_secret(
                token, salt,
                n=int(params["n"]), r=int(params["r"]),
                p=int(params["p"]), dklen=int(params["dklen"]),
            )
        except (ValueError, KeyError, MemoryError):
            continue
        if secrets.compare_digest(digest, expected) and found is None:
            found = i
    return found


def _prune(tokens: list[EnrollmentToken], now: int) -> list[EnrollmentToken]:
    cutoff = now - _RETENTION_SECONDS
    return [
        t for t in tokens
        if not ((t.used and t.used_at < cutoff) or (not t.used and t.expires_at < cutoff))
    ]
