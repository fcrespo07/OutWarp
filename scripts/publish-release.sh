#!/usr/bin/env bash
# OutWarp - publish a draft GitHub Release, after checking it is complete.
#
# Releases are immutable once published (repo setting): assets and tag can
# never change afterwards. So this is the only step that publishes, and it
# refuses unless the draft holds everything a release must carry:
#
#   - both wheels and at least one Windows installer for this version,
#   - SHA256SUMS.txt listing every one of them, with matching hashes,
#   - SHA256SUMS.txt.minisig valid for outwarp-release.pub, whose trusted
#     comment names this tag.
#
# Usage:
#   bash scripts/publish-release.sh v0.15.0          # asks before publishing
#   bash scripts/publish-release.sh v0.15.0 --yes    # no prompt
#
# Requires: gh (authenticated), minisign, sha256sum. See docs/RELEASE_SIGNING.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GH_REPO="fcrespo07/OutWarp"
PUBKEY="$REPO_ROOT/outwarp-release.pub"

die() { printf '  [X]  %s\n' "$*" >&2; exit 1; }
ok()  { printf '  [OK] %s\n' "$*"; }

TAG="${1:-}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]] || die "Usage: $0 vX.Y.Z [--yes]"
VERSION="${TAG#v}"
ASSUME_YES=0
[[ "${2:-}" == "--yes" ]] && ASSUME_YES=1

for tool in gh minisign sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || die "'$tool' not found"
done
[[ -f "$PUBKEY" ]] || die "$PUBKEY missing"

IS_DRAFT=$(gh -R "$GH_REPO" release view "$TAG" --json isDraft -q .isDraft 2>/dev/null) \
    || die "No release $TAG. Create the draft first (scripts/release.sh or the Release workflow)."
[[ "$IS_DRAFT" == "true" ]] || die "$TAG is already published."

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK" "$WORK.sums"' EXIT
gh -R "$GH_REPO" release download "$TAG" --dir "$WORK" >/dev/null
cd "$WORK"

ls outwarp_client-"$VERSION"-*.whl >/dev/null 2>&1 || die "client wheel for $VERSION missing"
ls outwarp_server-"$VERSION"-*.whl >/dev/null 2>&1 || die "server wheel for $VERSION missing"
ls OutWarpSetup-*"$VERSION"*.exe >/dev/null 2>&1 \
    || die "no Windows installer for $VERSION yet - wait for the Windows job"
[[ -f SHA256SUMS.txt ]] || die "SHA256SUMS.txt missing"
[[ -f SHA256SUMS.txt.minisig ]] \
    || die "SHA256SUMS.txt.minisig missing - sign the manifest first (docs/RELEASE_SIGNING.md)"
ok "all assets present"

VERIFY_OUT=$(minisign -V -p "$PUBKEY" -m SHA256SUMS.txt 2>&1) \
    || die "signature does not verify against outwarp-release.pub:
$VERIFY_OUT"
grep -q "Trusted comment:.*$TAG\b" <<<"$VERIFY_OUT" \
    || die "signature is valid but its trusted comment does not name $TAG:
$VERIFY_OUT"
ok "manifest signature valid for $TAG"

# The signature covers the bytes as uploaded; the Windows job writes them with
# CRLF, which sha256sum would read as part of each file name.
tr -d '\r' < SHA256SUMS.txt > "$WORK.sums"
LISTED=$(awk '{ n = $2; sub(/^\*/, "", n); print n }' "$WORK.sums")
for asset in *; do
    case "$asset" in SHA256SUMS.txt|SHA256SUMS.txt.minisig) continue ;; esac
    grep -Fxq -- "$asset" <<<"$LISTED" || die "$asset is not listed in SHA256SUMS.txt"
done
sha256sum --check --strict --quiet "$WORK.sums" || die "an asset does not match SHA256SUMS.txt"
ok "every asset listed and matching"

echo
echo "  Assets:"
ls -1 | sed 's/^/    /'
if [[ "$ASSUME_YES" != "1" ]]; then
    echo
    read -rp "Publish $TAG? It cannot be changed afterwards. [y/N]: " reply
    [[ "${reply,,}" =~ ^y(es)?$ ]] || die "Aborted"
fi

gh -R "$GH_REPO" release edit "$TAG" --draft=false --latest >/dev/null
ok "$TAG published: https://github.com/$GH_REPO/releases/tag/$TAG"
