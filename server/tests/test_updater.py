from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server import updater
from outwarp_server.updater import verify_wheel


def _wheel(tmp_path: Path, content: bytes = b"wheel-bytes") -> Path:
    p = tmp_path / "outwarp_server-0.4.2-py3-none-any.whl"
    p.write_bytes(content)
    return p


def test_verify_wheel_no_checksums_url_passes(tmp_path: Path) -> None:
    """Legacy releases without a SHA256SUMS asset: on a build with no release
    key, an empty URL skips verification rather than refuse to upgrade off them.
    Once a key is compiled in this becomes fatal — see TestManifestSignature."""
    wheel = _wheel(tmp_path)
    with patch.object(updater, "_MINISIGN_PUBLIC_KEY", ""):
        ok, detail = verify_wheel(wheel, wheel.name, "")
    assert ok is True
    assert "no SHA256SUMS" in detail


def test_verify_wheel_manifest_fetch_failure_is_rejected(tmp_path: Path) -> None:
    """A published SHA256SUMS URL that fails to fetch must NOT pass. Treating
    the network failure as 'no checksum' would let a MITM that selectively
    drops the manifest downgrade integrity verification on sudo
    outwarp-server update."""
    wheel = _wheel(tmp_path)

    import urllib.error
    with patch(
        "outwarp_server.updater.urllib.request.urlopen",
        side_effect=urllib.error.URLError("captive proxy 502"),
    ):
        ok, detail = verify_wheel(wheel, wheel.name, "https://x/SHA256SUMS.txt")
    assert ok is False
    assert "could not fetch" in detail.lower()


def test_verify_wheel_asset_not_listed_is_rejected(tmp_path: Path) -> None:
    """If SHA256SUMS exists but our wheel isn't in it → reject. The publisher
    would have listed every shipped asset; a missing entry is either the wrong
    release or a tampered manifest."""
    wheel = _wheel(tmp_path)

    resp = MagicMock()
    resp.__enter__ = lambda self: resp
    resp.__exit__ = lambda *a, **kw: None
    resp.read.return_value = b"0" * 64 + b"  something-else.whl\n"

    # No release key: these cover the hash logic. The signature path has its
    # own coverage in TestManifestSignature.
    with (
        patch.object(updater, "_MINISIGN_PUBLIC_KEY", ""),
        patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp),
    ):
        ok, detail = verify_wheel(wheel, wheel.name, "https://x/SHA256SUMS.txt")
    assert ok is False
    assert "not listed" in detail


def test_verify_wheel_hash_match(tmp_path: Path) -> None:
    """Happy path: manifest fetched, wheel listed, hash matches → ok=True."""
    wheel = _wheel(tmp_path)
    import hashlib
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()

    resp = MagicMock()
    resp.__enter__ = lambda self: resp
    resp.__exit__ = lambda *a, **kw: None
    resp.read.return_value = f"{expected}  {wheel.name}\n".encode()

    # No release key: these cover the hash logic. The signature path has its
    # own coverage in TestManifestSignature.
    with (
        patch.object(updater, "_MINISIGN_PUBLIC_KEY", ""),
        patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp),
    ):
        ok, detail = verify_wheel(wheel, wheel.name, "https://x/SHA256SUMS.txt")
    assert ok is True
    assert "verified" in detail


def test_verify_wheel_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    """Tampered or corrupt wheel: real mismatch → ok=False with a useful
    diagnostic that includes a hash-prefix."""
    wheel = _wheel(tmp_path)

    resp = MagicMock()
    resp.__enter__ = lambda self: resp
    resp.__exit__ = lambda *a, **kw: None
    resp.read.return_value = f"{'0' * 64}  {wheel.name}\n".encode()

    # No release key: these cover the hash logic. The signature path has its
    # own coverage in TestManifestSignature.
    with (
        patch.object(updater, "_MINISIGN_PUBLIC_KEY", ""),
        patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp),
    ):
        ok, detail = verify_wheel(wheel, wheel.name, "https://x/SHA256SUMS.txt")
    assert ok is False
    assert "mismatch" in detail


def test_apply_update_passes_timeout_to_subprocess(tmp_path: Path) -> None:
    """The pip subprocess.run must be invoked with a timeout — without one,
    a network stall during transitive-dep resolution hangs the updater
    indefinitely with the CLI frozen on 'Installing into venv (pip)…'."""
    from outwarp_server.updater import PIP_INSTALL_TIMEOUT, apply_update

    wheel = _wheel(tmp_path)
    with patch("outwarp_server.updater.subprocess.run") as run:
        apply_update(wheel, extras="tui")
    args, kwargs = run.call_args
    assert kwargs.get("timeout") == PIP_INSTALL_TIMEOUT
    assert kwargs.get("check") is True
    # The wheel-path-with-extras must be the last arg.
    cmd = args[0]
    assert cmd[-1] == f"{wheel}[tui]"


def test_apply_update_uses_pip_in_current_venv_not_pipx(tmp_path: Path) -> None:
    """Regression for the pipx migration: ``outwarp-server update`` must keep
    upgrading in place via ``sys.executable -m pip install --upgrade``.
    Shelling out to ``pipx upgrade`` would re-bootstrap the venv from the
    original spec and break the in-place upgrade contract the CLI advertises
    (and lose any operator-injected debug packages along the way)."""
    import sys as _sys

    from outwarp_server.updater import apply_update

    wheel = _wheel(tmp_path)
    with patch("outwarp_server.updater.subprocess.run") as run:
        apply_update(wheel)
    cmd = run.call_args[0][0]
    assert cmd[0] == _sys.executable, f"expected sys.executable, got {cmd[0]}"
    assert cmd[1:4] == ["-m", "pip", "install"], f"expected pip invocation, got {cmd[1:4]}"
    assert not any("pipx" in str(arg) for arg in cmd), f"pipx leaked into cmd: {cmd}"


# --- release signature (authenticity, not just integrity) ---

class TestManifestSignature:
    """Mirror of the client's coverage: SHA256SUMS travels with the binary, so
    only a signature made off the release infrastructure says who published it."""

    # Same offline-generated minisign fixtures the client tests use; the two
    # container parsers must agree or a signature valid for one would fail on
    # the other.
    PUB_KEY = (
        "untrusted comment: minisign public key 0E96ABF060984099\n"
        "RUQOlqvwYJhAmWt4JyEv2Xxt75wysIfZ32ktDAaFC2gRhALSBj63QJsJ\n"
    )
    MESSAGE = b"abc123  SHA256SUMS-like content\n"
    SIGNATURE = (
        "untrusted comment: signature from minisign secret key\n"
        "RUQOlqvwYJhAmc5sFUpL7qop9p/MRRkn/B8b3kvkyJd6WvHi8Ls/NIEf2lFtuv1OnlSgnilOaNnU"
        "zkrlm3CZ+rkP4pPCi81wKAE=\n"
        "trusted comment: timestamp:1767225600\tfile:SHA256SUMS.txt\n"
        "3vuif0C3Dhn0OngT6XXxJFeO6kfOCzbLF7XWj9SoMHI2nN7zUxLoNm+PzfsvQDtC1IEeNS3iMMLj"
        "r/WI973ZDg==\n"
    )

    def test_the_two_packages_agree_on_the_format(self) -> None:
        from outwarp_server.minisign import verify
        verify(self.MESSAGE, self.SIGNATURE, self.PUB_KEY)

    def test_tampered_manifest_is_rejected(self) -> None:
        from outwarp_server.minisign import MinisignError, verify
        with pytest.raises(MinisignError):
            verify(b"evil", self.SIGNATURE, self.PUB_KEY)

    def test_this_build_requires_signatures(self) -> None:
        assert updater.signing_configured() is True

    def test_a_build_without_a_key_still_accepts_unsigned_manifests(self) -> None:
        with patch.object(updater, "_MINISIGN_PUBLIC_KEY", ""):
            assert updater.signing_configured() is False
            updater._verify_manifest_signature("anything", "")

    def test_missing_signature_asset_is_fatal_once_a_key_exists(self) -> None:
        with (
            patch.object(updater, "_MINISIGN_PUBLIC_KEY", self.PUB_KEY),
            pytest.raises(ValueError, match="does not publish"),
        ):
            updater._verify_manifest_signature(self.MESSAGE.decode(), "")

    def test_verify_wheel_reports_a_bad_signature(self, tmp_path: Path) -> None:
        wheel = tmp_path / "outwarp_server-1.0-py3-none-any.whl"
        wheel.write_bytes(b"wheel bytes")
        digest = updater._sha256_file(wheel)
        manifest = f"{digest}  {wheel.name}\n"

        def _urlopen(req, **_kw):
            body = manifest if "sums" in req.full_url else self.SIGNATURE
            resp = MagicMock()
            resp.read.return_value = body.encode()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=None)
            return resp

        with (
            patch.object(updater, "_MINISIGN_PUBLIC_KEY", self.PUB_KEY),
            patch("outwarp_server.updater.urllib.request.urlopen", side_effect=_urlopen),
        ):
            ok, detail = updater.verify_wheel(
                wheel, wheel.name, "https://e/sums", "https://e/sig"
            )
        assert ok is False
        assert "signature verification" in detail

    def test_signature_url_is_picked_up_from_the_release(self) -> None:
        assets = [
            {"name": "outwarp_server-1.0-py3-none-any.whl",
             "browser_download_url": "https://e/w.whl", "size": 1},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://e/sums"},
            {"name": "SHA256SUMS.txt.minisig", "browser_download_url": "https://e/sig"},
        ]
        resp = MagicMock()
        resp.read.return_value = json.dumps({"tag_name": "v9.0.0", "assets": assets}).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=None)
        with patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp):
            info = updater.check_for_update("0.1.0")
        assert info["signature_url"] == "https://e/sig"
