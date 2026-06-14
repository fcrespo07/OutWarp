"""Authentication primitives for the embedded web admin panel.

The panel runs as root and is reachable over the network, so the front door
is a single admin token plus an in-memory session. Three pieces:

* :func:`generate_and_store_token` / :func:`verify_token` — the token is shown
  once on creation; only a salted scrypt hash is persisted (0o600).
* :class:`SessionStore` — opaque session ids handed out after a successful
  ``/auth``; validated on every ``/api`` and ``/events`` request.
* :class:`RateLimiter` — sliding-window lockout on ``/auth`` so the token can't
  be brute-forced over the wire.

None of this touches systemd/wg/wstunnel — it gates access to the ``Api`` that
does. Token + sessions only; for a single admin that's enough (no user/pass).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from outwarp_server.config import _atomic_write_secret

TOKEN_PREFIX = "ow_admin_"

# scrypt cost parameters. n=2**15 keeps a single verification well under ~100ms
# on a VPS core while making an offline brute-force of the (already
# high-entropy) token pointless.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def _token_path(config_dir: Path) -> Path:
    return config_dir / "admin_token.json"


def _hash_token(token: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=128 * _SCRYPT_N * _SCRYPT_R * 2,
    )


def token_is_set(config_dir: Path) -> bool:
    return _token_path(config_dir).exists()


def generate_and_store_token(config_dir: Path) -> str:
    """Mint a new admin token, persist only its salted hash, return the plaintext.

    The caller must show the returned token to the admin immediately — it is
    not recoverable afterwards.
    """
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    digest = _hash_token(token, salt)
    payload = json.dumps(
        {
            "version": 1,
            "salt": salt.hex(),
            "hash": digest.hex(),
            "scrypt": {"n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P, "dklen": _SCRYPT_DKLEN},
            "created": int(time.time()),
        },
        indent=2,
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_secret(_token_path(config_dir), payload)
    return token


def verify_token(config_dir: Path, token: str) -> bool:
    path = _token_path(config_dir)
    if not token or not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        salt = bytes.fromhex(raw["salt"])
        expected = bytes.fromhex(raw["hash"])
        params = raw.get("scrypt", {})
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    try:
        digest = hashlib.scrypt(
            token.encode("utf-8"),
            salt=salt,
            n=int(params.get("n", _SCRYPT_N)),
            r=int(params.get("r", _SCRYPT_R)),
            p=int(params.get("p", _SCRYPT_P)),
            dklen=int(params.get("dklen", _SCRYPT_DKLEN)),
            maxmem=128 * int(params.get("n", _SCRYPT_N)) * int(params.get("r", _SCRYPT_R)) * 2,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(digest, expected)


class SessionStore:
    """In-memory session table. Sessions die on daemon restart by design —
    a single admin re-authenticating is cheap, and there is no persisted
    session secret to leak."""

    _DEFAULT_TTL = 12 * 3600
    _REMEMBER_TTL = 30 * 86400

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}

    def create(self, remember: bool = False) -> str:
        sid = secrets.token_urlsafe(32)
        ttl = self._REMEMBER_TTL if remember else self._DEFAULT_TTL
        with self._lock:
            self._sessions[sid] = time.time() + ttl
        return sid

    def validate(self, sid: str | None) -> bool:
        if not sid:
            return False
        now = time.time()
        with self._lock:
            expiry = self._sessions.get(sid)
            if expiry is None:
                return False
            if expiry < now:
                del self._sessions[sid]
                return False
            return True

    def destroy(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)

    def purge_expired(self) -> None:
        now = time.time()
        with self._lock:
            dead = [s for s, exp in self._sessions.items() if exp < now]
            for s in dead:
                del self._sessions[s]


class RateLimiter:
    """Sliding-window failure counter per client IP.

    ``max_failures`` within ``window`` seconds triggers a ``lockout``. Reset on
    any successful auth so a legitimate admin who fat-fingered the token once
    isn't punished.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window: float = 300.0,
        lockout: float = 60.0,
    ) -> None:
        self._max = max_failures
        self._window = window
        self._lockout = lockout
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, ip: str) -> float:
        """Seconds the caller must wait, or 0 if not currently locked out."""
        now = time.time()
        with self._lock:
            until = self._locked_until.get(ip, 0.0)
            return max(0.0, until - now) if until > now else 0.0

    def register_failure(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            hits = [t for t in self._failures.get(ip, []) if t > now - self._window]
            hits.append(now)
            self._failures[ip] = hits
            if len(hits) >= self._max:
                self._locked_until[ip] = now + self._lockout
                self._failures[ip] = []

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)
            self._locked_until.pop(ip, None)
