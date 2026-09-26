"""Shared helpers for sign_release.py and publish_release.py.

Plain Python on purpose: the maintainer signs on Windows as well as Linux, and
the checks here (hashes, the minisign signature) must not depend on
sha256sum, bash or CRLF handling. Signature verification reuses the client's
own pure-Python minisign module, so what the scripts accept is exactly what
the updaters accept.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH_REPO = "fcrespo07/OutWarp"
MANIFEST = "SHA256SUMS.txt"
SIGNATURE = "SHA256SUMS.txt.minisig"
PUB_FILES = ("outwarp-release.pub", "outwarp-release-backup.pub")

sys.path.insert(0, str(ROOT / "client"))
from outwarp.minisign import (  # noqa: E402
    MinisignError,
    key_id_hex,
    parse_public_key,
    verify_any,
)

# gh is injected so the tests can stand in for GitHub.
Gh = Callable[[list[str]], str]


class ReleaseError(RuntimeError):
    pass


def run_gh(args: list[str]) -> str:
    try:
        done = subprocess.run(
            ["gh", "-R", GH_REPO, *args], capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise ReleaseError("gh (GitHub CLI) not found: run scripts/setup-release-signing.ps1 "
                           "on Windows, or install it from https://cli.github.com") from exc
    if done.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def trusted_keys() -> tuple[str, ...]:
    keys = tuple((ROOT / f).read_text(encoding="utf-8") for f in PUB_FILES if (ROOT / f).exists())
    if not keys:
        raise ReleaseError("no outwarp-release.pub in the repository root")
    return keys


def trusted_key_ids() -> list[str]:
    return [key_id_hex(parse_public_key(k)[0]) for k in trusted_keys()]


def require_draft(tag: str, gh: Gh) -> None:
    try:
        info = json.loads(gh(["release", "view", tag, "--json", "isDraft"]))
    except ReleaseError as exc:
        raise ReleaseError(
            f"no release {tag}: push the tag first (git tag {tag} && git push origin {tag})"
        ) from exc
    if not info.get("isDraft"):
        raise ReleaseError(
            f"{tag} is already published; releases are immutable, ship the next version instead"
        )


def check_signature(manifest: bytes, signature: str, tag: str) -> str:
    """Verify like the updaters do, plus the tag check; returns the key ID."""
    try:
        key_id = verify_any(manifest, signature, trusted_keys())
    except MinisignError as exc:
        raise ReleaseError(f"{SIGNATURE} does not verify: {exc}") from exc
    comment = next(
        (ln.split("trusted comment:", 1)[1].strip()
         for ln in signature.splitlines() if ln.startswith("trusted comment:")),
        "",
    )
    if tag not in comment.split():
        raise ReleaseError(
            f"the signature is valid but its trusted comment ({comment!r}) does not name {tag}"
        )
    return key_id


def version_of(tag: str) -> str:
    if not tag.startswith("v") or not tag[1:2].isdigit():
        raise ReleaseError(f"expected a tag like v0.15.0, got {tag!r}")
    return tag[1:]
