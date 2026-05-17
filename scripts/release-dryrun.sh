#!/usr/bin/env bash
# release-dryrun.sh — verify a release tag is safe to push
#
# Mirrors the validate + build steps of .github/workflows/release.yml so a
# maintainer can sanity-check locally before pushing the tag.
#
# Usage: bash scripts/release-dryrun.sh
# Exits 0 only if every check passes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }

step() { printf '\n=== %s ===\n' "$*"; }

step "1. Working tree is clean"
if [ -n "$(git status --porcelain)" ]; then
    red "FAIL: working tree has uncommitted changes."
    git status --short
    exit 1
fi
green "OK"

step "2. VERSION matches latest CHANGELOG section"
if [ ! -f VERSION ]; then
    red "FAIL: VERSION file missing"; exit 1
fi
VERSION="$(cat VERSION | tr -d '[:space:]')"
if [ -z "$VERSION" ]; then
    red "FAIL: VERSION is empty"; exit 1
fi
if ! grep -qE "^## \[${VERSION}\]" CHANGELOG.md; then
    red "FAIL: CHANGELOG.md has no section '## [${VERSION}]'"
    exit 1
fi
green "OK ($VERSION)"

step "3. Tag would-be 'v${VERSION}' does not yet exist"
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    yellow "Tag v${VERSION} already exists locally — re-running dry-run is fine, but push will be a no-op."
fi

step "4. Multi-arch buildx works (linux/amd64, linux/arm64)"
if ! docker buildx version >/dev/null 2>&1; then
    red "FAIL: docker buildx is required."
    exit 1
fi
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --build-arg "CLIFF_VERSION=${VERSION}" \
    --build-arg "CLIFF_REVISION=$(git rev-parse HEAD)" \
    --build-arg "CLIFF_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --file docker/Dockerfile \
    --tag "cliff:dryrun-${VERSION}" \
    .
green "OK"

step "5. Local amd64 image builds + Trivy CRITICAL scan"
docker buildx build \
    --load \
    --platform linux/amd64 \
    --build-arg "CLIFF_VERSION=${VERSION}" \
    --build-arg "CLIFF_REVISION=$(git rev-parse HEAD)" \
    --build-arg "CLIFF_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --file docker/Dockerfile \
    --tag "cliff:dryrun-${VERSION}-amd64" \
    .

if command -v trivy >/dev/null 2>&1; then
    trivy image \
        --severity CRITICAL \
        --exit-code 1 \
        --ignore-unfixed \
        "cliff:dryrun-${VERSION}-amd64"
    green "OK (no fixable CRITICAL CVEs)"
else
    yellow "Trivy not installed locally; skipping CVE scan. Install with: brew install aquasecurity/trivy/trivy"
fi

step "6. Image runs as non-root and /app/VERSION is correct"
ID_OUTPUT="$(docker run --rm "cliff:dryrun-${VERSION}-amd64" id -un)"
if [ "$ID_OUTPUT" != "cliff" ]; then
    red "FAIL: image runs as '$ID_OUTPUT', expected 'cliff'"
    exit 1
fi
IMAGE_VERSION="$(docker run --rm --entrypoint cat "cliff:dryrun-${VERSION}-amd64" /app/VERSION | tr -d '[:space:]')"
if [ "$IMAGE_VERSION" != "$VERSION" ]; then
    red "FAIL: /app/VERSION is '$IMAGE_VERSION', expected '$VERSION'"
    exit 1
fi
green "OK"

step "7. Tag set that the workflow would push"
SHORT_SHA="$(git rev-parse --short HEAD)"
case "$VERSION" in
    *-*)
        echo "  pre-release detected — 'latest' will NOT move."
        echo "  Tags: ${VERSION}, sha-${SHORT_SHA}"
        case "$VERSION" in
            *-alpha*) echo "        alpha (channel tag)" ;;
            *-beta*)  echo "        beta (channel tag)" ;;
            *-rc*)    echo "        rc (channel tag)" ;;
        esac
        ;;
    *)
        MAJOR="${VERSION%%.*}"
        MINOR="${VERSION#*.}"; MINOR="${MINOR%%.*}"
        echo "  stable release — 'latest' WILL move."
        echo "  Tags: ${VERSION}, ${MAJOR}.${MINOR}, ${MAJOR}, latest, sha-${SHORT_SHA}"
        ;;
esac

green "\nAll dry-run checks passed. To release: git tag -a v${VERSION} -m 'v${VERSION}' && git push origin v${VERSION}"
