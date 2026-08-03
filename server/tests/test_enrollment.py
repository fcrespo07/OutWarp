from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp_server import enrollment


class TestIssue:
    def test_returns_a_prefixed_plaintext_token(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop")
        assert token.startswith(enrollment.TOKEN_PREFIX)
        assert len(token) > len(enrollment.TOKEN_PREFIX) + 20

    def test_stores_only_a_hash(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop")
        raw = enrollment.store_path(tmp_path).read_text(encoding="utf-8")
        assert token not in raw
        stored = json.loads(raw)["tokens"][0]
        assert stored["client_name"] == "laptop"
        assert len(stored["token_hash"]) == 64  # 32-byte scrypt output, hex

    def test_store_is_0600(self, tmp_path: Path) -> None:
        import sys
        if sys.platform == "win32":
            pytest.skip("POSIX perm bits not enforced on NTFS")
        enrollment.issue(tmp_path, "laptop")
        assert enrollment.store_path(tmp_path).stat().st_mode & 0o777 == 0o600

    def test_reissuing_invalidates_the_previous_token(self, tmp_path: Path) -> None:
        """Re-running add-client after losing the .owcfg must not leave two live
        credentials for one slot."""
        first = enrollment.issue(tmp_path, "laptop")
        enrollment.issue(tmp_path, "laptop")
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path, first)

    def test_tokens_for_other_clients_survive(self, tmp_path: Path) -> None:
        phone = enrollment.issue(tmp_path, "phone")
        enrollment.issue(tmp_path, "laptop")
        assert enrollment.redeem(tmp_path, phone).client_name == "phone"

    def test_rejects_a_non_positive_ttl(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ttl_seconds"):
            enrollment.issue(tmp_path, "laptop", ttl_seconds=0)


class TestRedeem:
    def test_happy_path_returns_the_reserved_name(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop")
        assert enrollment.redeem(tmp_path, token).client_name == "laptop"

    def test_a_token_works_exactly_once(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop")
        enrollment.redeem(tmp_path, token)
        with pytest.raises(enrollment.TokenAlreadyUsedError, match="already redeemed"):
            enrollment.redeem(tmp_path, token)

    def test_the_second_attempt_names_interception_as_the_cause(self, tmp_path: Path) -> None:
        # This message is the entire detectability benefit of one-time tokens;
        # a generic "invalid token" would hide a stolen profile.
        token = enrollment.issue(tmp_path, "laptop")
        enrollment.redeem(tmp_path, token)
        with pytest.raises(enrollment.TokenAlreadyUsedError, match="intercepted"):
            enrollment.redeem(tmp_path, token)

    def test_expired_token_is_refused(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop", ttl_seconds=1)
        with (
            patch.object(enrollment.time, "time", return_value=time.time() + 3600),
            pytest.raises(enrollment.TokenExpiredError),
        ):
            enrollment.redeem(tmp_path, token)

    def test_unknown_token_is_refused(self, tmp_path: Path) -> None:
        enrollment.issue(tmp_path, "laptop")
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path, "ow_enroll_not-a-real-token")

    def test_empty_token_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path, "")

    def test_missing_store_is_refused_not_crashed(self, tmp_path: Path) -> None:
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path / "nope", "ow_enroll_whatever")

    def test_a_corrupt_store_does_not_admit_anyone(self, tmp_path: Path) -> None:
        enrollment.store_path(tmp_path).write_text("{ not json", encoding="utf-8")
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path, "ow_enroll_whatever")


class TestPendingAndRevoke:
    def test_pending_lists_only_live_tokens(self, tmp_path: Path) -> None:
        enrollment.issue(tmp_path, "phone")
        used = enrollment.issue(tmp_path, "laptop")
        enrollment.redeem(tmp_path, used)
        assert [t.client_name for t in enrollment.pending(tmp_path)] == ["phone"]

    def test_pending_excludes_expired(self, tmp_path: Path) -> None:
        enrollment.issue(tmp_path, "phone", ttl_seconds=1)
        with patch.object(enrollment.time, "time", return_value=time.time() + 3600):
            assert enrollment.pending(tmp_path) == []

    def test_revoke_kills_an_outstanding_token(self, tmp_path: Path) -> None:
        token = enrollment.issue(tmp_path, "laptop")
        assert enrollment.revoke(tmp_path, "laptop") == 1
        with pytest.raises(enrollment.TokenUnknownError):
            enrollment.redeem(tmp_path, token)

    def test_revoke_leaves_other_clients_alone(self, tmp_path: Path) -> None:
        phone = enrollment.issue(tmp_path, "phone")
        enrollment.issue(tmp_path, "laptop")
        enrollment.revoke(tmp_path, "laptop")
        assert enrollment.redeem(tmp_path, phone).client_name == "phone"
