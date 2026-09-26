"""Sign a draft release's SHA256SUMS.txt and attach the signature.

    python scripts/sign_release.py v0.15.0
    python scripts/sign_release.py v0.15.0 --key D:\\outwarp-release-backup.key

Run it on the maintainer's machine once the Release workflow has finished
(the Windows job merges the installers' hashes into the manifest last). It
downloads the manifest from the draft, signs it with minisign (which asks for
the key's password), checks the result exactly as the updaters will, and
uploads SHA256SUMS.txt.minisig. Publishing is a separate step:
scripts/publish_release.py. See docs/RELEASE_SIGNING.md.

The key never leaves this machine; nothing here sends it anywhere.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_tools import (
    MANIFEST,
    SIGNATURE,
    Gh,
    ReleaseError,
    check_signature,
    require_draft,
    run_gh,
    version_of,
)

DEFAULT_KEY = Path.home() / ".minisign" / "outwarp-release.key"


def sign(tag: str, key: Path, minisign: str, gh: Gh = run_gh,
         run: callable = subprocess.run) -> str:
    version = version_of(tag)
    if not key.exists():
        raise ReleaseError(f"secret key not found: {key} (use --key)")
    require_draft(tag, gh)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        gh(["release", "download", tag, "--pattern", MANIFEST, "--dir", str(work), "--clobber"])
        manifest = work / MANIFEST
        if not manifest.exists():
            raise ReleaseError(f"the draft has no {MANIFEST} yet: wait for the Release workflow")
        listed = manifest.read_text(encoding="utf-8", errors="replace")
        if "OutWarpSetup-" not in listed or version not in listed:
            raise ReleaseError(
                f"{MANIFEST} lists no Windows installer for {version} yet: wait for the "
                "Windows job to finish, it merges its hashes last"
            )

        done = run(
            [minisign, "-S", "-s", str(key), "-m", str(manifest), "-t", f"OutWarp {tag}"],
            check=False,
        )
        signature = work / SIGNATURE
        if done.returncode != 0 or not signature.exists():
            raise ReleaseError("minisign did not sign (wrong password?)")

        key_id = check_signature(manifest.read_bytes(),
                                 signature.read_text(encoding="utf-8"), tag)
        gh(["release", "upload", tag, str(signature), "--clobber"])
    return key_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="release tag, e.g. v0.15.0")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY,
                        help=f"minisign secret key (default: {DEFAULT_KEY})")
    parser.add_argument("--minisign", default=shutil.which("minisign") or "minisign",
                        help="minisign executable")
    args = parser.parse_args(argv)
    try:
        key_id = sign(args.tag, args.key, args.minisign)
    except ReleaseError as exc:
        print(f"  [X] {exc}", file=sys.stderr)
        return 1
    print(f"  [OK] {SIGNATURE} signed with key {key_id} and attached to the {args.tag} draft")
    print(f"       next: python scripts/publish_release.py {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
