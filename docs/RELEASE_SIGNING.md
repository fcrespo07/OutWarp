# Release signing

OutWarp publishes `SHA256SUMS.txt` with every release and both updaters check the
download against it. That proves the file arrived intact. It does **not** prove
who published it: the manifest lives in the same GitHub release as the binary and
is fetched over the same trust path, so anyone who can publish a release — a
stolen `GITHUB_TOKEN`, a compromised account, a poisoned workflow — can publish a
matching manifest alongside a malicious installer.

Signing the manifest with [minisign](https://jedisct1.github.io/minisign/) closes
that gap. The public halves are compiled into the client and the server; the
private halves never touch the release infrastructure.

## The one rule

**A signing key never goes into a GitHub secret.**

If the key lives where CI can reach it, then whoever can publish a release can
also sign it, and the signature proves nothing that the manifest did not already
prove. The whole value of this step is that compromising the publishing pipeline
is *not* enough. Sign on your own machine, upload the `.minisig` as a release
asset, and keep the secret keys offline and backed up.

## The keys

Both updaters trust **two** keys and accept a signature from either (chosen by
the key ID in the signature):

Both were generated on 2026-09-28 and ship from 0.15.0.

| Key | Public half | Secret half | Used for |
|---|---|---|---|
| **Primary** `A2E04F7F69ABA94F` | `outwarp-release.pub` | `%USERPROFILE%\.minisign\outwarp-release.key` (Windows) or `~/.minisign/outwarp-release.key`, plus an encrypted copy in the maintainer's password manager | every release |
| **Backup** `C864B6A98619FAC9` | `outwarp-release-backup.pub` | offline USB drive(s) only, never left on a disk | only if the primary is lost |

Each secret key is encrypted with its own password (minisign's scrypt box); both
passwords live in the password manager. The backup exists because a single key
is a single point of failure: losing it means no installed copy can verify an
update any more, which is exactly what happened to the first key (see
"History"). With a backup, losing the primary costs one release signed with the
backup and an ordinary rotation.

Tests keep the two `.pub` files and the compiled keys in sync
(`client/tests/test_release_keys.py`, `server/tests/test_release_keys.py`).

## Setting up a signing machine

**Windows 10/11** — from a checkout of the repository, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-release-signing.ps1
```

It installs Git, GitHub CLI, Python and minisign with winget (falling back to
minisign's official release zip), prints their versions and logs `gh` in. Then
put the primary secret key at `%USERPROFILE%\.minisign\outwarp-release.key`
(from the password manager copy).

**Linux** — install `minisign`, `gh` (logged in) and Python 3.11+ from the
distribution, and put the key at `~/.minisign/outwarp-release.key`.

## Every release

Releases are **immutable once published** (repository setting "Enable release
immutability"): after publishing, no asset can be added, replaced or deleted
and the tag cannot move. So everything — wheels, installers, the final
`SHA256SUMS.txt` and its `.minisig` — goes into a **draft**, and publishing is
the last step. Drafts are invisible to the updaters (`releases/latest` skips
them), so nobody is offered a half-finished release.

1. **Draft.** Push the tag: `git tag vX.Y.Z` then `git push origin vX.Y.Z`
   (on Linux, `bash scripts/release.sh` does the same after a local build). The
   *Release* workflow builds the wheels into a draft and then runs the Windows
   installer job, which adds the three `.exe` editions and merges their hashes
   into `SHA256SUMS.txt`. Wait for both jobs: the manifest is final only then.

2. **Sign**: `python scripts/sign_release.py vX.Y.Z`. It downloads the manifest
   from the draft, refuses if the Windows installers are not in it yet, runs
   `minisign -S` with a trusted comment `OutWarp vX.Y.Z` (minisign asks for the
   key's password), verifies the result the way the updaters will and attaches
   `SHA256SUMS.txt.minisig` to the draft. `--key PATH` signs with another key
   file, e.g. the backup.

3. **Publish**: `python scripts/publish_release.py vX.Y.Z`. It downloads the
   whole draft and refuses unless both wheels and a Windows installer for that
   version are there, every asset is listed in `SHA256SUMS.txt` with a matching
   hash, and the `.minisig` verifies against a trusted key with a trusted comment
   naming the tag. Only then, after a confirmation, does it flip the draft to
   published (and *latest*). It needs `gh` and Python only.

If anything is wrong after publishing, the release cannot be fixed: ship the
next patch version instead.

## What the client enforces

| Situation | Result |
|---|---|
| Release has no `SHA256SUMS.txt` | **refused** |
| Manifest present, no `.minisig` | **refused** |
| `.minisig` present but unfetchable | **refused** |
| `.minisig` made by a key the build does not trust | **refused** |
| Signature or trusted comment altered | **refused** |
| Signed by the primary or the backup key, hashes match | update proceeds |

A missing signature is treated exactly like a bad one on purpose. If deleting a
file from the release were enough to skip the check, the check would be
opt-out — for the attacker. Since 0.15.0 there is no fail-open path at all.

## Replacing a key

- **Planned rotation** (or the backup was used): generate a new pair with
  `minisign -G`, add its public key to both updaters **next to** the one in use,
  ship a release signed with the current key, and only in a later release drop
  the old key. Installed copies then always trust the key that signs their next
  update.
- **Primary lost or compromised**: sign the next release with the backup
  (`sign_release.py --key <usb>\outwarp-release-backup.key`); that release drops
  the lost key and adds a new primary, and a new backup is generated. A
  compromised key must be removed in that same release.
- **No trusted key left**: no installed copy can be updated automatically. Ship
  a release with new keys and tell users to update by hand once.
  `scripts\setup-release-signing.ps1 -NewKeys` generates a new primary and
  backup and prints the public material to put in the updaters.

## History

- `3E1FCD8BF652EC28` — the first key, generated 2026-08-03, sole trusted key of
  releases 0.11.0–0.14.0. **Lost on 2026-09-26** when the maintainer's laptop
  was reinstalled, with no backup. Not known to be compromised. Clients and
  servers 0.11–0.14 trust only this key, so they cannot verify 0.15.0 and must
  be updated by hand once. Its public half stays at
  `keys/retired/outwarp-release-3E1FCD8BF652EC28.pub` so signatures on 0.11–0.14
  can still be checked.
- `A2E04F7F69ABA94F` (primary) and `C864B6A98619FAC9` (backup) — generated
  2026-09-28 on the maintainer's Windows machine with
  `scripts\setup-release-signing.ps1 -NewKeys`; trusted from 0.15.0.

## What this does not cover

`installer/linux/install.sh` checks the wheel against `SHA256SUMS.txt` but does
not verify the signature — it would need the `minisign` binary present before
OutWarp is installed. That path is bootstrapped with `curl … | sudo bash` from
`raw.githubusercontent.com`, so it already extends full trust to GitHub and a
signature would add little there. The in-app updaters (`outwarp update`,
`outwarp-server update`, and the GUI's update button) are the paths that matter,
because they run unattended on machines that are already installed, and those do
verify.

## Verifying a download by hand

```bash
minisign -V -p outwarp-release.pub -m SHA256SUMS.txt      # or outwarp-release-backup.pub
sha256sum -c SHA256SUMS.txt --ignore-missing
```

On Windows: `minisign -V -p outwarp-release.pub -m SHA256SUMS.txt` and
`Get-FileHash OutWarpSetup-X.Y.Z.exe` against the line in the manifest.
