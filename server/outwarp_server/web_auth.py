"""Authentication primitives for the embedded web admin panel.

The panel runs as root and is reachable over the network, so the front door
is a single admin token plus a session cookie. Three pieces:

* :func:`generate_and_store_token` / :func:`verify_token` — the token is shown
  once on creation; only a salted scrypt hash is persisted (0o600).
* :class:`SessionStore` — opaque session ids handed out after a successful
  ``/auth``; validated on every ``/api`` and ``/events`` request, persisted
  hashed so a panel restart doesn't log the admin out.
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
from typing import Any

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


def hash_secret(
    secret: str,
    salt: bytes,
    *,
    n: int = _SCRYPT_N,
    r: int = _SCRYPT_R,
    p: int = _SCRYPT_P,
    dklen: int = _SCRYPT_DKLEN,
) -> bytes:
    """scrypt with this module's cost parameters.

    Shared with :mod:`outwarp_server.enrollment`, which stores one-time tokens
    the same way, so both live-token stores agree on cost and neither has to
    keep its own copy of the parameters.
    """
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=128 * n * r * 2,
    )


def scrypt_params() -> dict[str, int]:
    return {"n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P, "dklen": _SCRYPT_DKLEN}


def _hash_token(token: str, salt: bytes) -> bytes:
    return hash_secret(token, salt)


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
    """Panel sessions, persisted so a restart of the panel (an update, a pod
    reschedule) doesn't log the admin out.

    Only ``sha256(session id)`` is written (0o600, next to the admin token),
    so the file is useless to someone who reads it: the cookie value can't be
    rebuilt from it. Each session is bound to the admin token it was opened
    with; rotating the token (``outwarp-server admin-token --rotate``) ends
    every open session, in this process or any other. Without ``path`` the
    store stays in memory (tests, callers that don't want persistence).
    """

    DEFAULT_TTL = 12 * 3600
    REMEMBER_TTL = 30 * 86400
    _FILE_NAME = "panel_sessions.json"

    def __init__(self, config_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        # sha256(sid) -> {"exp": epoch seconds, "token": token fingerprint}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._config_dir = config_dir
        self._path = config_dir / self._FILE_NAME if config_dir else None
        self._fp_cache: tuple[tuple[int, int, int], str] | None = None
        self._load()

    @classmethod
    def ttl(cls, remember: bool) -> int:
        return cls.REMEMBER_TTL if remember else cls.DEFAULT_TTL

    @staticmethod
    def _key(sid: str) -> str:
        return hashlib.sha256(sid.encode("utf-8")).hexdigest()

    def _token_fingerprint(self) -> str:
        """Changes whenever the admin token is rotated; "" without a token file."""
        if self._config_dir is None:
            return ""
        path = _token_path(self._config_dir)
        try:
            st = path.stat()
        except OSError:
            return ""
        # The token is rewritten atomically (new inode), so a rotation within
        # the filesystem's mtime granularity is still seen.
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        if self._fp_cache and self._fp_cache[0] == stamp:
            return self._fp_cache[1]
        try:
            salt = json.loads(path.read_text(encoding="utf-8"))["salt"]
        except (OSError, ValueError, KeyError, TypeError):
            return ""
        fp = hashlib.sha256(str(salt).encode("utf-8")).hexdigest()[:32]
        self._fp_cache = (stamp, fp)
        return fp

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            entries = raw.get("sessions", {})
        except FileNotFoundError:
            return
        except (OSError, ValueError, AttributeError):
            # A corrupt file costs a login, nothing more.
            return
        now = time.time()
        for key, entry in entries.items() if isinstance(entries, dict) else ():
            try:
                exp = float(entry["exp"])
                token = str(entry["token"])
            except (KeyError, TypeError, ValueError):
                continue
            if exp > now:
                self._sessions[str(key)] = {"exp": exp, "token": token}

    def _save_locked(self) -> None:
        if self._path is None:
            return
        payload = json.dumps({"version": 1, "sessions": self._sessions}, indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_secret(self._path, payload)
        except OSError:
            # Sessions keep working in memory; they just won't survive a restart.
            pass

    def create(self, remember: bool = False) -> str:
        sid = secrets.token_urlsafe(32)
        entry = {"exp": time.time() + self.ttl(remember), "token": self._token_fingerprint()}
        with self._lock:
            self._sessions[self._key(sid)] = entry
            self._save_locked()
        return sid

    def validate(self, sid: str | None) -> bool:
        if not sid:
            return False
        key = self._key(sid)
        now = time.time()
        current = self._token_fingerprint()
        with self._lock:
            entry = self._sessions.get(key)
            if entry is None:
                return False
            if entry["exp"] < now or entry["token"] != current:
                del self._sessions[key]
                self._save_locked()
                return False
            return True

    def destroy(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            if self._sessions.pop(self._key(sid), None) is not None:
                self._save_locked()

    def purge_expired(self) -> None:
        now = time.time()
        current = self._token_fingerprint()
        with self._lock:
            dead = [k for k, e in self._sessions.items()
                    if e["exp"] < now or e["token"] != current]
            for k in dead:
                del self._sessions[k]
            if dead:
                self._save_locked()


def client_ip(headers: Any, direct_ip: str, *, behind_reverse_proxy: bool) -> str:
    """The address to rate-limit/log a request by.

    A direct connection is identified by its TCP peer address. Behind a
    reverse proxy (Caddy, in the transport's "acme" branch — see FIX-08 in
    docs/history/OutWarp-fix-plan.md) the listener binds loopback and every real client
    shares that one address, so a naive rate limiter keyed on `direct_ip`
    collapses into a single shared bucket: a handful of failures from ANY
    client locks everyone else out too. Caddy's `reverse_proxy` appends the
    real client to `X-Forwarded-For`, so behind a proxy that header's *last*
    entry is authoritative instead — earlier entries are whatever the client
    itself claimed and are not trustworthy.

    Only call this with `behind_reverse_proxy=True` when the listener
    actually binds loopback behind our own Caddyfile — nothing untrusted can
    reach it directly to forge the header. The self-signed branch binds
    publicly instead, where `behind_reverse_proxy` is always False and
    `direct_ip` (the real TCP peer) is used as-is.
    """
    if behind_reverse_proxy:
        forwarded = headers.get("X-Forwarded-For", "") or ""
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return direct_ip or "?"


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
