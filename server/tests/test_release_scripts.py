"""scripts/sign_release.py and scripts/publish_release.py against a fake gh.

They replaced the bash publish-release.sh so releases can be signed and
published from Windows; these are the scenarios that script was tested with.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from outwarp_server.minisign import format_public_key, generate_keypair, sign

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import publish_release  # noqa: E402
import release_tools  # noqa: E402
import sign_release  # noqa: E402

TAG = "v9.9.0"


@pytest.fixture
def keys(monkeypatch):
    kid, priv, pub = generate_keypair()
    monkeypatch.setattr(release_tools, "trusted_keys", lambda: (format_public_key(kid, pub),))
    return kid, priv


def _assets(version: str = "9.9.0") -> dict[str, bytes]:
    return {
        f"outwarp_client-{version}-py3-none-any.whl": b"client wheel",
        f"outwarp_server-{version}-py3-none-any.whl": b"server wheel",
        f"OutWarpSetup-{version}.exe": b"installer",
    }


def _manifest(assets: dict[str, bytes], crlf: bool = True) -> bytes:
    eol = "\r\n" if crlf else "\n"
    return "".join(f"{hashlib.sha256(b).hexdigest()}  {n}{eol}" for n, b in assets.items()).encode()


class FakeGh:
    def __init__(self, files: dict[str, bytes], *, draft: bool = True) -> None:
        self.files, self.draft, self.calls = dict(files), draft, []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["release", "view"]:
            return json.dumps({"isDraft": self.draft})
        if args[:2] == ["release", "download"]:
            out = Path(args[args.index("--dir") + 1])
            pattern = args[args.index("--pattern") + 1] if "--pattern" in args else None
            for name, data in self.files.items():
                if pattern in (None, name):
                    (out / name).write_bytes(data)
            return ""
        if args[:2] == ["release", "upload"]:
            path = Path(args[3])
            self.files[path.name] = path.read_bytes()
            return ""
        if args[:2] == ["release", "edit"]:
            self.draft = False
            return ""
        raise AssertionError(args)


def _signed_draft(keys, *, comment: str = f"OutWarp {TAG}", assets=None) -> FakeGh:
    kid, priv = keys
    assets = assets or _assets()
    manifest = _manifest(assets)
    files = {**assets, "SHA256SUMS.txt": manifest,
             "SHA256SUMS.txt.minisig": sign(manifest, kid, priv, trusted_comment=comment).encode()}
    return FakeGh(files)


# ── publish ──────────────────────────────────────────────────────────────────

def test_publishes_a_complete_signed_draft(keys) -> None:
    gh = _signed_draft(keys)
    publish_release.publish(TAG, assume_yes=True, gh=gh)
    assert gh.draft is False
    assert ["release", "edit", TAG, "--draft=false", "--latest"] in gh.calls


def test_refuses_an_already_published_release(keys) -> None:
    gh = _signed_draft(keys)
    gh.draft = False
    with pytest.raises(release_tools.ReleaseError, match="already published"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_refuses_without_the_windows_installer(keys) -> None:
    assets = {k: v for k, v in _assets().items() if not k.endswith(".exe")}
    gh = _signed_draft(keys, assets=assets)
    with pytest.raises(release_tools.ReleaseError, match="Windows installer"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)
    assert gh.draft is True


def test_refuses_an_unsigned_manifest(keys) -> None:
    gh = _signed_draft(keys)
    del gh.files["SHA256SUMS.txt.minisig"]
    with pytest.raises(release_tools.ReleaseError, match="sign_release.py"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_refuses_a_signature_from_an_untrusted_key(keys) -> None:
    other = generate_keypair()
    gh = _signed_draft((other[0], other[1]))
    with pytest.raises(release_tools.ReleaseError, match="does not trust"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_refuses_a_signature_for_another_tag(keys) -> None:
    gh = _signed_draft(keys, comment="OutWarp v9.8.0")
    with pytest.raises(release_tools.ReleaseError, match="does not name"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_refuses_an_asset_that_does_not_match(keys) -> None:
    gh = _signed_draft(keys)
    gh.files["OutWarpSetup-9.9.0.exe"] = b"tampered"
    with pytest.raises(release_tools.ReleaseError, match="does not match"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_refuses_an_unlisted_asset(keys) -> None:
    gh = _signed_draft(keys)
    gh.files["extra.zip"] = b"?"
    with pytest.raises(release_tools.ReleaseError, match="not listed"):
        publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_asks_before_publishing(keys) -> None:
    gh = _signed_draft(keys)
    with pytest.raises(release_tools.ReleaseError, match="aborted"):
        publish_release.publish(TAG, gh=gh, ask=lambda _prompt: "n")
    assert gh.draft is True


# ── sign ─────────────────────────────────────────────────────────────────────

def _fake_minisign(keys, comment_override: str | None = None):
    kid, priv = keys

    def run(cmd, check=False):
        manifest = Path(cmd[cmd.index("-m") + 1])
        comment = comment_override or cmd[cmd.index("-t") + 1]
        sig = sign(manifest.read_bytes(), kid, priv, trusted_comment=comment)
        manifest.with_name(manifest.name + ".minisig").write_text(sig)
        return SimpleNamespace(returncode=0)

    return run


def test_sign_uploads_a_verified_signature(keys, tmp_path) -> None:
    key = tmp_path / "outwarp-release.key"
    key.write_text("secret")
    gh = FakeGh({**_assets(), "SHA256SUMS.txt": _manifest(_assets())})

    key_id = sign_release.sign(TAG, key, "minisign", gh=gh, run=_fake_minisign(keys))

    assert key_id == release_tools.key_id_hex(keys[0])
    assert "SHA256SUMS.txt.minisig" in gh.files
    # And what it uploaded is what publish accepts.
    publish_release.publish(TAG, assume_yes=True, gh=gh)


def test_sign_waits_for_the_windows_job(keys, tmp_path) -> None:
    key = tmp_path / "k.key"
    key.write_text("secret")
    wheels_only = {k: v for k, v in _assets().items() if k.endswith(".whl")}
    gh = FakeGh({**wheels_only, "SHA256SUMS.txt": _manifest(wheels_only)})
    with pytest.raises(release_tools.ReleaseError, match="Windows job"):
        sign_release.sign(TAG, key, "minisign", gh=gh, run=_fake_minisign(keys))


def test_sign_refuses_a_missing_key(keys, tmp_path) -> None:
    gh = FakeGh({})
    with pytest.raises(release_tools.ReleaseError, match="secret key not found"):
        sign_release.sign(TAG, tmp_path / "nope.key", "minisign", gh=gh)
