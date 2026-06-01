#!/usr/bin/env bash
# OutWarp - Linux release helper
#
# Builds the client and server wheels and publishes them as GitHub Release
# assets. The version is read from client/pyproject.toml (must match server's).
#
# Usage:
#   bash scripts/release.sh              # build + tag + publish
#   bash scripts/release.sh --dry-run    # build only (wheels left in dist/)
#
# Requires: python3.11+, the 'build' PyPI package (auto-installed if missing),
#           and the 'gh' CLI authenticated against the OutWarp repo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GH_REPO="fcrespo07/OutWarp"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# ─── UI helpers ───────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
    YELLOW=$'\033[33m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi

info()  { printf '%s==>%s %s\n' "$CYAN" "$RESET" "$*"; }
ok()    { printf '  %s[OK]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '  %s[!]%s  %s\n' "$YELLOW" "$RESET" "$*"; }
err()   { printf '  %s[X]%s  %s\n' "$RED" "$RESET" "$*" >&2; }
die()   { err "$*"; exit 1; }

# ─── Version detection ────────────────────────────────────────────────────────
read_version() {
    # Greps the first `version = "x.y.z"` line in a pyproject.toml.
    # Avoids tomllib so this script works under Python 3.10 / older systems.
    # `tr -d '\r'` defends against CRLF line endings someone may have introduced
    # by editing the file in a Windows IDE.
    grep -m1 '^version = ' "$1" | tr -d '\r' | sed -E 's/^version = "([^"]+)"$/\1/'
}

read_dunder_version() {
    # Greps `__version__ = "x.y.z"` from a package __init__.py — the runtime
    # source of truth that the updater compares against `latest` on GitHub.
    # If this drifts from pyproject.toml, the wheel ships v0.4.2 but
    # `outwarp-cli --version` keeps reporting 0.4.1 and `update --check-only`
    # never proposes upgrading off the published release.
    grep -m1 '^__version__ = ' "$1" | tr -d '\r' | sed -E 's/^__version__ = "([^"]+)"$/\1/'
}

CLIENT_VERSION=$(read_version "$REPO_ROOT/client/pyproject.toml")
SERVER_VERSION=$(read_version "$REPO_ROOT/server/pyproject.toml")
CLIENT_DUNDER=$(read_dunder_version "$REPO_ROOT/client/outwarp/__init__.py")
SERVER_DUNDER=$(read_dunder_version "$REPO_ROOT/server/outwarp_server/__init__.py")
[[ -n "$CLIENT_VERSION" ]] || die "Could not read version from client/pyproject.toml"
[[ -n "$SERVER_VERSION" ]] || die "Could not read version from server/pyproject.toml"
[[ -n "$CLIENT_DUNDER" ]] || die "Could not read __version__ from client/outwarp/__init__.py"
[[ -n "$SERVER_DUNDER" ]] || die "Could not read __version__ from server/outwarp_server/__init__.py"
[[ "$CLIENT_VERSION" == "$SERVER_VERSION" ]] || \
    die "Version mismatch: client=$CLIENT_VERSION server=$SERVER_VERSION. Sync them first."
[[ "$CLIENT_VERSION" == "$CLIENT_DUNDER" ]] || \
    die "Client version drift: pyproject.toml=$CLIENT_VERSION but __version__=$CLIENT_DUNDER. The updater compares the dunder against the GitHub tag — bump both together."
[[ "$SERVER_VERSION" == "$SERVER_DUNDER" ]] || \
    die "Server version drift: pyproject.toml=$SERVER_VERSION but __version__=$SERVER_DUNDER. Sync them before releasing."

VERSION="$CLIENT_VERSION"
TAG="v$VERSION"

# ─── Pre-flight ───────────────────────────────────────────────────────────────
info "OutWarp release ${BOLD}${TAG}${RESET}"

PYTHON_BIN="${PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "python3 not found"

if ! "$PYTHON_BIN" -c "import build" 2>/dev/null; then
    info "Installing 'build' package..."
    "$PYTHON_BIN" -m pip install --quiet --user build || die "Could not install 'build'"
fi

# ─── Build wheels ─────────────────────────────────────────────────────────────
DIST_DIR="$REPO_ROOT/dist"
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

info "Building outwarp-client wheel..."
"$PYTHON_BIN" -m build --wheel --outdir "$DIST_DIR" "$REPO_ROOT/client" >/dev/null \
    || die "outwarp-client wheel build failed"
ok "Built: $(ls "$DIST_DIR"/outwarp_client-*.whl 2>/dev/null | xargs -n1 basename)"

info "Building outwarp-server wheel..."
"$PYTHON_BIN" -m build --wheel --outdir "$DIST_DIR" "$REPO_ROOT/server" >/dev/null \
    || die "outwarp-server wheel build failed"
ok "Built: $(ls "$DIST_DIR"/outwarp_server-*.whl 2>/dev/null | xargs -n1 basename)"

# Sanity check filenames carry the expected version
for kind in client server; do
    expected="$DIST_DIR/outwarp_${kind}-${VERSION}-py3-none-any.whl"
    [[ -f "$expected" ]] || die "Expected wheel not produced: $expected"
done

# ─── Checksums ────────────────────────────────────────────────────────────────
info "Generating SHA256SUMS.txt..."
(
    cd "$DIST_DIR"
    sha256sum outwarp_client-*.whl outwarp_server-*.whl > SHA256SUMS.txt
)
cat "$DIST_DIR/SHA256SUMS.txt"
ok "SHA256SUMS.txt written"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    info "${BOLD}Dry run${RESET} - wheels left in $DIST_DIR/"
    info "Inspect with: ls -lh $DIST_DIR"
    exit 0
fi

# ─── Publish gating ───────────────────────────────────────────────────────────
command -v gh >/dev/null 2>&1 || die "'gh' CLI not found. Install from https://cli.github.com"
gh auth status >/dev/null 2>&1 || die "gh not authenticated. Run: gh auth login"

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    git -C "$REPO_ROOT" status --short
    die "Working tree is dirty. Commit or stash changes before releasing."
fi

CURRENT_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    warn "Releasing from non-main branch '$CURRENT_BRANCH'"
    read -rp "Continue anyway? [y/N]: " reply
    [[ "${reply,,}" =~ ^y(es)?$ ]] || die "Aborted by user"
fi

# ─── Tag ──────────────────────────────────────────────────────────────────────
if git -C "$REPO_ROOT" rev-parse "$TAG" >/dev/null 2>&1; then
    ok "Tag $TAG already exists locally"
else
    info "Creating tag $TAG..."
    git -C "$REPO_ROOT" tag "$TAG"
    ok "Tagged $TAG"
fi

# Push the tag if remote doesn't have it yet
if ! git -C "$REPO_ROOT" ls-remote --tags origin "refs/tags/$TAG" | grep -q "$TAG"; then
    info "Pushing tag $TAG to origin..."
    git -C "$REPO_ROOT" push origin "$TAG"
    ok "Tag pushed"
else
    ok "Tag $TAG already on origin"
fi

# ─── GitHub Release ───────────────────────────────────────────────────────────
ASSETS=(
    "$DIST_DIR"/outwarp_client-*.whl
    "$DIST_DIR"/outwarp_server-*.whl
    "$DIST_DIR/SHA256SUMS.txt"
)

if gh -R "$GH_REPO" release view "$TAG" >/dev/null 2>&1; then
    info "Release $TAG exists - uploading wheel assets (--clobber)..."
    gh -R "$GH_REPO" release upload "$TAG" "${ASSETS[@]}" --clobber
    ok "Assets uploaded to existing release"
else
    info "Creating release $TAG..."
    gh -R "$GH_REPO" release create "$TAG" \
        --title "$TAG" \
        --notes "Linux wheels for OutWarp $TAG.

Install / upgrade with the one-liner:
\`\`\`
curl -fsSL https://raw.githubusercontent.com/fcrespo07/OutWarp/main/installer/linux/install.sh | sudo bash
\`\`\`

Or upgrade in place:
\`\`\`
sudo outwarp-cli update      # client
sudo outwarp-server update   # server
\`\`\`" \
        "${ASSETS[@]}"
    ok "Release $TAG created"
fi

echo
printf '%s%s[DONE]%s OutWarp %s published.\n' "$BOLD" "$GREEN" "$RESET" "$TAG"
printf '  %sClient wheel:%s https://github.com/%s/releases/download/%s/outwarp_client-%s-py3-none-any.whl\n' \
    "$DIM" "$RESET" "$GH_REPO" "$TAG" "$VERSION"
printf '  %sServer wheel:%s https://github.com/%s/releases/download/%s/outwarp_server-%s-py3-none-any.whl\n' \
    "$DIM" "$RESET" "$GH_REPO" "$TAG" "$VERSION"
