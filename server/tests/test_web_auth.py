from __future__ import annotations

import sys
import time

import pytest

from outwarp_server.web_auth import (
    RateLimiter,
    SessionStore,
    generate_and_store_token,
    token_is_set,
    verify_token,
)


def test_token_roundtrip_and_rotation(tmp_path):
    assert token_is_set(tmp_path) is False
    token = generate_and_store_token(tmp_path)
    assert token.startswith("ow_admin_")
    assert token_is_set(tmp_path) is True
    assert verify_token(tmp_path, token) is True
    assert verify_token(tmp_path, "ow_admin_wrong") is False

    rotated = generate_and_store_token(tmp_path)
    assert rotated != token
    assert verify_token(tmp_path, token) is False
    assert verify_token(tmp_path, rotated) is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits not enforced on NTFS")
def test_token_file_is_0600(tmp_path):
    import os
    import stat

    generate_and_store_token(tmp_path)
    mode = stat.S_IMODE(os.stat(tmp_path / "admin_token.json").st_mode)
    assert mode == 0o600


def test_rate_limiter_locks_out_after_threshold():
    rl = RateLimiter(max_failures=3, window=300, lockout=60)
    ip = "1.2.3.4"
    assert rl.retry_after(ip) == 0
    rl.register_failure(ip)
    rl.register_failure(ip)
    assert rl.retry_after(ip) == 0
    rl.register_failure(ip)
    assert rl.retry_after(ip) > 0
    # A different IP is unaffected.
    assert rl.retry_after("5.6.7.8") == 0


def test_rate_limiter_reset_clears_lockout():
    rl = RateLimiter(max_failures=2, window=300, lockout=60)
    ip = "1.2.3.4"
    rl.register_failure(ip)
    rl.register_failure(ip)
    assert rl.retry_after(ip) > 0
    rl.reset(ip)
    assert rl.retry_after(ip) == 0


def test_session_lifecycle():
    store = SessionStore()
    sid = store.create(remember=False)
    assert store.validate(sid) is True
    assert store.validate("nope") is False
    assert store.validate(None) is False
    store.destroy(sid)
    assert store.validate(sid) is False


def test_session_expiry():
    store = SessionStore()
    sid = store.create(remember=False)
    # Force the stored expiry into the past.
    store._sessions[sid] = time.time() - 1
    assert store.validate(sid) is False
