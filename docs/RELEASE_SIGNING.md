# Release signing

OutWarp publishes `SHA256SUMS.txt` with every release and both updaters check the
download against it. That proves the file arrived intact. It does **not** prove
who published it: the manifest lives in the same GitHub release as the binary and
is fetched over the same trust path, so anyone who can publish a release — a
stolen `GITHUB_TOKEN`, a compromised account, a poisoned workflow — can publish a
matching manifest alongside a malicious installer.

Signing the manifest with [minisign](https://jedisct1.github.io/minisign/) closes
that gap. The public half is compiled into the client and the server; the private
half never touches the release infrastructure.

## The one rule

**The signing key does not go into a GitHub secret.**

If the key lives where CI can reach it, then whoever can publish a release can
also sign it, and the signature proves nothing that the manifest did not already
prove. The whole value of this step is that compromising the publishing pipeline
is *not* enough. Sign on your own machine, upload the `.minisig` as a release
asset, and keep the secret key offline (password-protected, backed up somewhere
that is not the same laptop).

## One-time setup — already done

> **The key exists.** ID `3E1FCD8BF652EC28`, generated 2026-08-03, public half
> committed as `outwarp-release.pub` and compiled into both updaters. The secret
> key lives at `~/.minisign/outwarp-release.key` on the maintainer's machine.
> The section below is kept for the day it has to be replaced — see "If the key
> is lost or compromised" at the end.

```bash
# 1. Generate the release keypair. Choose a strong password when prompted.
minisign -G -p outwarp-release.pub -s ~/.minisign/outwarp-release.key

# 2. Print the public key and copy the base64 line.
cat outwarp-release.pub
```

Paste both lines (the `untrusted comment:` line and the base64 line) into
`_MINISIGN_PUBLIC_KEY` in **both** of:

- `client/outwarp/updater.py`
- `server/outwarp_server/updater.py`

as a single string with an embedded newline, e.g.

```python
_MINISIGN_PUBLIC_KEY = (
    "untrusted comment: minisign public key 1A2B3C4D5E6F7788\n"
    "RWQaKzxNXm93iL...\n"
)
```

Commit that change. From the first release built with it, an unsigned or
wrongly-signed manifest is rejected — see "Cut-over" below for why that ordering
matters.

Also commit `outwarp-release.pub` to the repository root so users can verify
downloads by hand.

## Every release

Releases are **immutable once published** (repository setting "Enable release
immutability"): after publishing, no asset can be added, replaced or deleted
and the tag cannot move. So everything — wheels, installers, the final
`SHA256SUMS.txt` and its `.minisig` — goes into a **draft**, and publishing is
the last step. Drafts are invisible to the updaters (`releases/latest` skips
them), so nobody is offered a half-finished release.

1. **Draft.** Push the tag (`bash scripts/release.sh` does it, or
   `git tag vX.Y.Z && git push origin vX.Y.Z`). The *Release* workflow builds
   the wheels into a draft and then runs the Windows installer job, which adds
   the three `.exe` editions and merges their hashes into `SHA256SUMS.txt`.
   Wait for both jobs to finish: the manifest is final only then.

2. **Sign**, on your machine:

   ```bash
   tag=v0.15.0

   # Fetch the final manifest from the draft.
   gh release download "$tag" --pattern SHA256SUMS.txt --clobber

   # Sign it, with a trusted comment that names the release.
   minisign -S -s ~/.minisign/outwarp-release.key \
            -m SHA256SUMS.txt \
            -t "OutWarp $tag"

   # Attach the signature to the draft.
   gh release upload "$tag" SHA256SUMS.txt.minisig --clobber
   ```

3. **Publish**: `bash scripts/publish-release.sh "$tag"`. It downloads the
   draft and refuses to publish unless both wheels and a Windows installer for
   that version are there, every asset is listed in `SHA256SUMS.txt` with a
   matching hash, and the `.minisig` verifies against `outwarp-release.pub`
   with a trusted comment naming `$tag`. Only then does it flip the draft to
   published (and *latest*).

If anything is wrong after publishing, the release cannot be fixed: ship the
next patch version instead.

`minisign -S` writes `SHA256SUMS.txt.minisig`; the asset name matters, both
updaters look for exactly that.

## What the client enforces

| Situation | Before a key is configured | After |
|---|---|---|
| Release has no `SHA256SUMS.txt` | update proceeds unverified | **refused** |
| Manifest present, no `.minisig` | update proceeds, hash-checked | **refused** |
| `.minisig` present but unfetchable | n/a | **refused** |
| `.minisig` signed by another key | n/a | **refused** |
| Trusted comment altered | n/a | **refused** |
| Everything checks out | update proceeds | update proceeds |

A missing signature is treated exactly like a bad one on purpose. If deleting a
file from the release were enough to skip the check, the check would be
opt-out — for the attacker.

## Cut-over (done)

The key shipped in 0.11.0 and every release since carries a valid `.minisig`.
In 0.15.0 the fail-open branch was removed from both updaters: a release with no
`SHA256SUMS.txt`, or with an unsigned or wrongly-signed one, is always rejected,
and a build without a compiled-in key refuses every manifest. Clients older than
0.11.0 still ignore signatures; they can only be fixed by updating them.

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
minisign -V -p outwarp-release.pub -m SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt --ignore-missing
```

## If the key is lost or compromised

There is no revocation list. Generate a new keypair, ship a release whose client
carries the new public key, and announce it — users on the old key will keep
trusting the old one until they update, which is the same trust-on-first-use
property the initial key has. Keep the compromised key's public half documented
so an old signature can still be identified.
