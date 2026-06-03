#!/usr/bin/env sh
# Cliff native installer (macOS + glibc Linux).
#
# This is the recommended path for new users; Docker stays available as the
# secondary path (Windows + advanced users). Run it like this:
#
#   curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install-local.sh | sh
#
# Pin a specific version:
#
#   curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install-local.sh | CLIFF_VERSION=0.1.6 sh
#
# Environment overrides:
#   CLIFF_HOME            Install root (default: $HOME/.cliff)
#   CLIFF_VERSION         Pin to a specific release tag (default: latest)
#   CLIFF_REPO            github owner/name (default: cliff-security/cliff)
#   CLIFF_LOCAL_TARBALL   Path to a local tarball (skip download — for CI/dev)
#
# Idempotent: re-running upgrades the install without touching ~/.cliff/data
# or ~/.cliff/config.

set -eu

CLIFF_REPO="${CLIFF_REPO:-cliff-security/cliff}"
CLIFF_HOME="${CLIFF_HOME:-$HOME/.cliff}"
APP_DIR="${CLIFF_HOME}/app"
BACKEND_DIR="${APP_DIR}/backend"
BIN_DIR="${CLIFF_HOME}/bin"
DATA_DIR="${CLIFF_HOME}/data"
CONFIG_DIR="${CLIFF_HOME}/config"
ENV_FILE="${CONFIG_DIR}/cliff.env"
LOCAL_BIN="${HOME}/.local/bin"
LAUNCHER="${LOCAL_BIN}/cliffsec"
CLI_VENV="${CLIFF_HOME}/cli-venv"

# ---- pretty output ---------------------------------------------------------

if [ -t 1 ]; then
  BOLD=$(printf '\033[1m')
  DIM=$(printf '\033[2m')
  RED=$(printf '\033[31m')
  GREEN=$(printf '\033[32m')
  YELLOW=$(printf '\033[33m')
  BLUE=$(printf '\033[34m')
  RESET=$(printf '\033[0m')
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi

say()  { printf '%s==>%s %s\n' "${BLUE}" "${RESET}" "$1"; }
ok()   { printf '%s ok%s  %s\n' "${GREEN}" "${RESET}" "$1"; }
warn() { printf '%swarn%s %s\n' "${YELLOW}" "${RESET}" "$1" >&2; }
fail() { printf '%sFAIL%s %s\n' "${RED}" "${RESET}" "$1" >&2; exit 1; }

# ---- platform detection ----------------------------------------------------
#
# Per-binary arch detection lives in install-scanners.sh; here we only
# sort by OS family and reject the environments we know don't work.

case "$(uname -s)" in
  Darwin) OS="darwin" ;;
  Linux)  OS="linux" ;;
  *) fail "unsupported OS: $(uname -s). Use Docker on Windows / other platforms." ;;
esac

case "$(uname -m)" in
  x86_64|amd64|arm64|aarch64) : ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

# Trivy releases are glibc-only — fail early on Alpine/musl.
if [ "${OS}" = "linux" ] && command -v ldd >/dev/null 2>&1; then
  if ! ldd --version 2>&1 | grep -qiE 'glibc|gnu libc'; then
    fail "Alpine/musl Linux is not supported. Use the Docker image instead."
  fi
fi

# ---- preflight -------------------------------------------------------------

say "Checking prerequisites"

missing=""
for cmd in curl tar git; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing="${missing} ${cmd}"
  fi
done

# gh is a *hard* runtime dependency: the remediation agents shell out to
# `gh pr create`. Don't let users get partway through an install only to
# have remediations fail mysteriously later.
if ! command -v gh >/dev/null 2>&1; then
  missing="${missing} gh"
fi

if [ -n "${missing# }" ]; then
  printf '\n  Missing prerequisites:%s\n\n' "${missing}"
  if [ "${OS}" = "darwin" ]; then
    printf '  Install via Homebrew:\n    brew install%s\n\n' "${missing}"
  else
    printf '  Install via your package manager (apt example):\n'
    printf '    sudo apt-get update && sudo apt-get install -y%s\n\n' "${missing}"
    printf '  Note: gh on Debian/Ubuntu requires the GitHub apt repo:\n'
    printf '    https://github.com/cli/cli/blob/trunk/docs/install_linux.md\n\n'
  fi
  fail "Install the missing tools and re-run."
fi
ok "curl, tar, git, gh available"

# ---- uv --------------------------------------------------------------------

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (manages Python without sudo)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Source the env script that uv's installer drops, so uv is on PATH for
  # the rest of this shell.
  if [ -f "${HOME}/.local/bin/env" ]; then
    # shellcheck disable=SC1091
    . "${HOME}/.local/bin/env"
  fi
  if ! command -v uv >/dev/null 2>&1; then
    PATH="${HOME}/.local/bin:${PATH}"
    export PATH
  fi
fi
command -v uv >/dev/null 2>&1 || fail "uv install failed — see https://docs.astral.sh/uv/getting-started/installation/"
ok "uv $(uv --version | awk '{print $2}')"

say "Installing managed Python 3.11"
uv python install 3.11 >/dev/null
ok "Python 3.11 ready"

# ---- download tarball ------------------------------------------------------

mkdir -p "${CLIFF_HOME}" "${BIN_DIR}" "${DATA_DIR}" "${CONFIG_DIR}" "${LOCAL_BIN}"

VERSION="${CLIFF_VERSION:-latest}"

if [ -n "${CLIFF_LOCAL_TARBALL:-}" ]; then
  say "Using local tarball ${CLIFF_LOCAL_TARBALL}"
  TARBALL="${CLIFF_LOCAL_TARBALL}"
else
  # The v0.2.0 -> v0.2.1 rename changed the release asset from
  # `cliff-<ver>.tar.gz` to `cliffsec-<ver>.tar.gz`. Try the new name first;
  # if a pre-rename tag is pinned via CLIFF_VERSION, fall back to the old
  # name. POSIX shell can't semver-compare portably, so we let curl decide.
  if [ "${VERSION}" = "latest" ]; then
    URL="https://github.com/${CLIFF_REPO}/releases/latest/download/cliffsec.tar.gz"
    FALLBACK_URL="https://github.com/${CLIFF_REPO}/releases/latest/download/cliff.tar.gz"
  else
    URL="https://github.com/${CLIFF_REPO}/releases/download/v${VERSION}/cliffsec-${VERSION}.tar.gz"
    FALLBACK_URL="https://github.com/${CLIFF_REPO}/releases/download/v${VERSION}/cliff-${VERSION}.tar.gz"
  fi
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "${TMPDIR}"' EXIT
  TARBALL="${TMPDIR}/cliffsec.tar.gz"
  say "Downloading ${URL}"
  if ! curl -fsSL "${URL}" -o "${TARBALL}" 2>/dev/null; then
    say "Asset not found at ${URL}; trying pre-rename name."
    curl -fsSL "${FALLBACK_URL}" -o "${TARBALL}" \
      || fail "Download failed (tried ${URL} and ${FALLBACK_URL}). Check the URL or pass CLIFF_VERSION=<tag> for a specific release."
    URL="${FALLBACK_URL}"
  fi

  # Best-effort SHA256 verification — the same release uploads
  # `cliffsec.tar.gz.sha256` next to the tarball.
  SUM_URL="${URL}.sha256"
  if curl -fsSL "${SUM_URL}" -o "${TARBALL}.sha256" 2>/dev/null; then
    EXPECTED=$(awk '{print $1}' "${TARBALL}.sha256")
    if command -v shasum >/dev/null 2>&1; then
      ACTUAL=$(shasum -a 256 "${TARBALL}" | awk '{print $1}')
    elif command -v sha256sum >/dev/null 2>&1; then
      ACTUAL=$(sha256sum "${TARBALL}" | awk '{print $1}')
    else
      ACTUAL=""
    fi
    if [ -n "${ACTUAL}" ] && [ -n "${EXPECTED}" ]; then
      if [ "${ACTUAL}" = "${EXPECTED}" ]; then
        ok "tarball SHA256 matches"
      else
        fail "tarball SHA256 mismatch — expected ${EXPECTED}, got ${ACTUAL}"
      fi
    fi
  fi
fi

say "Extracting to ${APP_DIR}"
# Wipe the previous app/ contents on upgrade, but leave bin/ data/ config/ alone.
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}"
tar -xzf "${TARBALL}" -C "${APP_DIR}" --strip-components=0
ok "extracted"

# ---- backend venv (uv-managed) ---------------------------------------------

say "Installing backend dependencies"
cd "${BACKEND_DIR}"
uv sync --frozen --no-dev --quiet \
  || fail "uv sync failed — see ${BACKEND_DIR}/uv.lock and try again."
ok "backend venv at ${BACKEND_DIR}/.venv"

# ---- scanners (trivy, semgrep) ---------------------------------------------
#
# Invoke the helper script directly so its `#!/usr/bin/env bash` shebang
# takes effect. Calling `sh script.sh` would force the system /bin/sh which
# is dash on Debian/Ubuntu — and the helper uses bashisms (`set -o pipefail`,
# `[[ ... ]]`, arrays).

say "Installing scanners (trivy, semgrep)"
chmod +x "${APP_DIR}/scripts/install-scanners.sh"
# CLIFF_SCANNER_VERIFY=warn until .scanner-versions ships real SHAs.
# Keeps the strict-mode contract for the future without blocking installs today.
CLIFF_BIN_DIR="${BIN_DIR}" \
CLIFF_SCANNER_VERIFY=warn \
  "${APP_DIR}/scripts/install-scanners.sh" \
  || fail "install-scanners.sh failed."

# ---- credential vault key + env file ---------------------------------------

if [ ! -f "${ENV_FILE}" ]; then
  say "Generating credential vault key"
  if command -v openssl >/dev/null 2>&1; then
    KEY=$(openssl rand -base64 32)
  else
    KEY=$(uv run --quiet python -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())')
  fi
  cat > "${ENV_FILE}" <<EOF
# Cliff local install — environment overrides loaded by \`cliffsec start\`.
# This file lives outside the app directory so reinstalls don't clobber it.
#
# Required:
CLIFF_CREDENTIAL_KEY=${KEY}

# Optional — set your LLM key here, OR paste it into the Settings UI after
# starting the server (the UI persists it to the encrypted credential vault).
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=

# Optional — bind host/port. The CLI defaults match these.
# CLIFF_APP_HOST=127.0.0.1
# CLIFF_APP_PORT=8000
EOF
  chmod 600 "${ENV_FILE}"
  ok "wrote ${ENV_FILE}"
else
  ok "${ENV_FILE} preserved"
fi

# ---- cliffsec CLI venv + launcher symlink --------------------------------

say "Installing cliffsec CLI"
# We install the CLI into its own venv (separate from the backend venv) so it
# can be upgraded independently. cli/ source ships in the tarball.
rm -rf "${CLI_VENV}"
uv venv --python 3.11 --quiet "${CLI_VENV}"
uv pip install --python "${CLI_VENV}/bin/python" --quiet "${APP_DIR}/cli" \
  || fail "uv pip install of cli/ failed."

# Clean up the pre-rename `cliff` symlink (v0.2.0 and earlier).
# `ln -sf` only replaces the target it's pointed at — without this the old
# `cliff` symlink would survive an upgrade and stay on PATH.
rm -f "${LOCAL_BIN}/cliff"
# A pinned pre-rename install (e.g. CLIFF_VERSION=0.2.0) lands a `bin/cliff`
# console-script in the venv, not `bin/cliffsec`. Pick whichever exists so
# the launcher symlink is never dangling.
CLI_BIN="${CLI_VENV}/bin/cliffsec"
if [ ! -x "${CLI_BIN}" ] && [ -x "${CLI_VENV}/bin/cliff" ]; then
  CLI_BIN="${CLI_VENV}/bin/cliff"
fi
[ -x "${CLI_BIN}" ] || fail "Installed CLI binary not found in ${CLI_VENV}/bin (expected cliffsec or cliff)."
ln -sf "${CLI_BIN}" "${LAUNCHER}"
ok "cliffsec CLI at ${LAUNCHER}"

# ---- final UX --------------------------------------------------------------

echo
case ":${PATH}:" in
  *":${LOCAL_BIN}:"*) : ;;
  *)
    warn "${LOCAL_BIN} is not in your PATH."
    printf '  Add this to your shell rc (~/.zshrc or ~/.bashrc):\n\n'
    # shellcheck disable=SC2016
    printf '    %sexport PATH="$HOME/.local/bin:$PATH"%s\n\n' "${BOLD}" "${RESET}"
    ;;
esac

printf '%sCliff is installed.%s\n\n' "${BOLD}" "${RESET}"
printf '  %sStart:%s     cliffsec start --detach\n' "${DIM}" "${RESET}"
printf '  %sStatus:%s    cliffsec doctor\n' "${DIM}" "${RESET}"
printf '  %sLogs:%s      cliffsec logs -f\n' "${DIM}" "${RESET}"
printf '  %sStop:%s      cliffsec stop\n' "${DIM}" "${RESET}"
echo
printf '  Open %shttp://127.0.0.1:8000%s after starting, then paste your\n' "${BLUE}" "${RESET}"
printf '  Anthropic or OpenAI API key in the Settings page.\n'
echo
