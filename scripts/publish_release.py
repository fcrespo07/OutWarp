"""Publish a draft GitHub Release, after checking it is complete and signed.

    python scripts/publish_release.py v0.15.0          # asks before publishing
    python scripts/publish_release.py v0.15.0 --yes    # no prompt

Releases are immutable once published (repository setting): assets and tag
can never change afterwards. So this is the only step that publishes, and it
refuses unless the draft holds everything a release must carry:

  - both wheels and at least one Windows installer for this version,
  - SHA256SUMS.txt listing every one of them, with matching hashes,
  - SHA256SUMS.txt.minisig valid for a trusted release key (the same check
    the updaters make), whose trusted comment names this tag.

Needs gh (authenticated) and Python; no minisign, bash or sha256sum.
See docs/RELEASE_SIGNING.md.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

from release_tools import (
    GH_REPO,
    MANIFEST,
    SIGNATURE,
    Gh,
    ReleaseError,
    check_signature,
    require_draft,
    run_gh,
    version_of,
)


def _parse_manifest(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()  # the Windows job writes CRLF
        if not line:
            continue
        digest, _, name = line.partition(" ")
        sums[name.strip().lstrip("*")] = digest.lower()
    return sums


def check_draft(tag: str, work: Path) -> tuple[list[str], str]:
    """Validate downloaded assets in ``work``; returns (asset names, key ID)."""
    version = version_of(tag)
    names = sorted(p.name for p in work.iterdir() if p.is_file())

    def need(prefix: str, suffix: str, what: str) -> None:
        if not any(n.startswith(prefix) and version in n and n.endswith(suffix) for n in names):
            raise ReleaseError(f"{what} for {version} missing")

    need("outwarp_client-", ".whl", "client wheel")
    need("outwarp_server-", ".whl", "server wheel")
    need("OutWarpSetup-", ".exe", "Windows installer (wait for the Windows job)")
    if MANIFEST not in names:
        raise ReleaseError(f"{MANIFEST} missing")
    if SIGNATURE not in names:
        raise ReleaseError(f"{SIGNATURE} missing: run python scripts/sign_release.py {tag}")

    manifest = (work / MANIFEST).read_bytes()
    key_id = check_signature(manifest, (work / SIGNATURE).read_text(encoding="utf-8"), tag)

    sums = _parse_manifest(manifest.decode("utf-8", "replace"))
    for name in names:
        if name in (MANIFEST, SIGNATURE):
            continue
        if name not in sums:
            raise ReleaseError(f"{name} is not listed in {MANIFEST}")
        actual = hashlib.sha256((work / name).read_bytes()).hexdigest()
        if actual != sums[name]:
            raise ReleaseError(f"{name} does not match {MANIFEST}")
    return names, key_id


def publish(tag: str, *, assume_yes: bool = False, gh: Gh = run_gh,
            ask: callable = input) -> None:
    require_draft(tag, gh)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        gh(["release", "download", tag, "--dir", str(work)])
        names, key_id = check_draft(tag, work)

    print("  [OK] all assets present, listed and matching")
    print(f"  [OK] manifest signed by trusted key {key_id} for {tag}")
    print("\n  Assets:\n" + "\n".join(f"    {n}" for n in names))
    if not assume_yes:
        reply = ask(f"\nPublish {tag}? It cannot be changed afterwards. [y/N]: ")
        if reply.strip().lower() not in ("y", "yes", "s", "si", "sí"):
            raise ReleaseError("aborted")
    gh(["release", "edit", tag, "--draft=false", "--latest"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="release tag, e.g. v0.15.0")
    parser.add_argument("--yes", action="store_true", help="publish without asking")
    args = parser.parse_args(argv)
    try:
        publish(args.tag, assume_yes=args.yes)
    except ReleaseError as exc:
        print(f"  [X] {exc}", file=sys.stderr)
        return 1
    print(f"  [OK] {args.tag} published: https://github.com/{GH_REPO}/releases/tag/{args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
