#!/usr/bin/env bash
# Build the OpenSec local-install tarball.
#
# Output:
#   dist/opensec-<version>.tar.gz
#   dist/opensec-<version>.tar.gz.sha256
#
# Layout inside the tarball (extracts directly under the install's app dir):
#   backend/                pyproject.toml, uv.lock, opensec/
#   frontend/dist/          prebuilt SPA (vite output)
#   cli/                    opensec_cli source + pyproject.toml
#   scripts/                install-opencode.sh, install-scanners.sh
#   .opencode-version
#   .scanner-versions
#   VERSION
#   README-LOCAL-INSTALL.md (short pointer)
#
# Usage:
#   scripts/build-tarball.sh                    # auto-detect version from VERSION
#   scripts/build-tarball.sh 0.1.6              # explicit version
#   SKIP_FRONTEND_BUILD=1 scripts/build-tarball.sh  # use existing frontend/dist
#
# In CI: invoked by .github/workflows/release.yml. The frontend build runs
# in a Node 20 step that completes before this script runs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VERSION="${1:-$(tr -d '[:space:]' < VERSION)}"
if [[ -z "${VERSION}" ]]; then
  echo "error: cannot resolve version. Pass it explicitly or populate VERSION." >&2
  exit 1
fi

DIST_DIR="${REPO_ROOT}/dist"
STAGE_DIR="$(mktemp -d -t opensec-build-XXXXXXXX)"
trap 'rm -rf "${STAGE_DIR}"' EXIT
mkdir -p "${DIST_DIR}"

echo "==> staging in ${STAGE_DIR}"

# ---- frontend --------------------------------------------------------------

if [[ "${SKIP_FRONTEND_BUILD:-0}" != "1" ]]; then
  echo "==> building frontend"
  (cd frontend && npm ci --silent && npm run build --silent)
fi

if [[ ! -f frontend/dist/index.html ]]; then
  echo "error: frontend/dist/index.html missing — run \`npm run build\` in frontend/ first" >&2
  exit 1
fi

# Helper: remove caches/build artifacts from a staged tree. Portable across
# GNU/BSD find — `tar --exclude` glob semantics differ between the two, so we
# stage with cp and prune afterwards.
prune_caches() {
  local root="$1"
  find "${root}" \
    \( -type d \( \
         -name '.venv' -o \
         -name '.pytest_cache' -o \
         -name '.ruff_cache' -o \
         -name '__pycache__' -o \
         -name 'node_modules' -o \
         -name '.mypy_cache' -o \
         -name '.tox' -o \
         -name 'dist' -o \
         -name 'build' \
       \) \
       -prune -exec rm -rf {} + \
    \) -o \
    \( -type d -name '*.egg-info' -prune -exec rm -rf {} + \)
}

# ---- backend (source only — venv is created at install time) ---------------

cp -R backend "${STAGE_DIR}/backend"
rm -rf "${STAGE_DIR}/backend/tests"
prune_caches "${STAGE_DIR}/backend"

# ---- frontend (dist only — source is not shipped) -------------------------

mkdir -p "${STAGE_DIR}/frontend"
cp -R frontend/dist "${STAGE_DIR}/frontend/dist"

# ---- cli source (installed at install time into its own venv) -------------

cp -R cli "${STAGE_DIR}/cli"
rm -rf "${STAGE_DIR}/cli/tests"
prune_caches "${STAGE_DIR}/cli"

# ---- scripts (just the two install helpers — install-local.sh isn't needed
# at runtime, it's how the user got here in the first place) -----------------

mkdir -p "${STAGE_DIR}/scripts"
cp scripts/install-opencode.sh "${STAGE_DIR}/scripts/"
cp scripts/install-scanners.sh "${STAGE_DIR}/scripts/"
chmod +x "${STAGE_DIR}/scripts/"*.sh

# ---- pinned versions + version metadata -----------------------------------

cp .opencode-version "${STAGE_DIR}/"
cp .scanner-versions "${STAGE_DIR}/"
echo "${VERSION}" > "${STAGE_DIR}/VERSION"

cat > "${STAGE_DIR}/README-LOCAL-INSTALL.md" <<'EOF'
This tarball is the OpenSec native install payload.

If you got here directly, you almost certainly want the installer instead:

    curl -fsSL https://github.com/galanko/opensec/releases/latest/download/install-local.sh | sh

The installer downloads this tarball, extracts it under ~/.opensec/app/,
sets up a uv-managed Python venv, installs the opencode/trivy/semgrep
binaries via the bundled scripts, and drops `opensec` into ~/.local/bin/.
EOF

# ---- archive ---------------------------------------------------------------

ARCHIVE_NAME="opensec-${VERSION}.tar.gz"
ARCHIVE_PATH="${DIST_DIR}/${ARCHIVE_NAME}"
echo "==> writing ${ARCHIVE_PATH}"
tar -czf "${ARCHIVE_PATH}" -C "${STAGE_DIR}" .

# Compute SHA256 next to the archive.
if command -v shasum >/dev/null 2>&1; then
  (cd "${DIST_DIR}" && shasum -a 256 "${ARCHIVE_NAME}") > "${ARCHIVE_PATH}.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  (cd "${DIST_DIR}" && sha256sum "${ARCHIVE_NAME}") > "${ARCHIVE_PATH}.sha256"
else
  echo "warn: no shasum/sha256sum found — skipping .sha256 generation" >&2
fi

# Also produce a stable-name copy so /releases/latest/download/opensec.tar.gz
# resolves cleanly. CI uploads both.
cp "${ARCHIVE_PATH}" "${DIST_DIR}/opensec.tar.gz"
if [[ -f "${ARCHIVE_PATH}.sha256" ]]; then
  cp "${ARCHIVE_PATH}.sha256" "${DIST_DIR}/opensec.tar.gz.sha256"
  # Rewrite the filename inside the .sha256 file so `shasum -c` works against
  # the stable-name copy too.
  awk -v new="opensec.tar.gz" '{print $1"  "new}' "${ARCHIVE_PATH}.sha256" \
    > "${DIST_DIR}/opensec.tar.gz.sha256"
fi

echo
echo "Built:"
ls -lh "${DIST_DIR}"/opensec*.tar.gz "${DIST_DIR}"/opensec*.sha256 2>/dev/null || true
