from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from outwarp_server.updater import verify_wheel


def _wheel(tmp_path: Path, content: bytes = b"wheel-bytes") -> Path:
    p = tmp_path / "outwarp_server-0.4.2-py3-none-any.whl"
    p.write_bytes(content)
    return p


def test_verify_wheel_no_checksums_url_passes(tmp_path: Path) -> None:
    """Legacy releases without a SHA256SUMS asset: empty URL → skip with True
    rather than refuse to upgrade off them."""
    wheel = _wheel(tmp_path)
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

    with patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp):
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

    with patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp):
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

    with patch("outwarp_server.updater.urllib.request.urlopen", return_value=resp):
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
