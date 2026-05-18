#!/usr/bin/env sh
# Cliff one-line installer
#
# Usage:
#   curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install.sh | sh
#
# Or to install a specific version:
#   curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install.sh | CLIFF_VERSION=0.1.0-alpha sh
#
# Environment overrides:
#   CLIFF_HOME            Install directory (default: $HOME/cliff)
#   CLIFF_VERSION         Image tag to install (default: latest)
#   ANTHROPIC_API_KEY       Skips the interactive key prompt
#   OPENAI_API_KEY          Skips the interactive key prompt
#   CLIFF_NON_INTERACTIVE Set to 1 to skip all prompts (CI/scripts)
#
# This script is idempotent: re-running pulls the latest image, leaves
# .env and the data volume untouched.

set -eu

REPO_OWNER="galanko"
REPO_NAME="cliff"
GH_REPO="https://github.com/${REPO_OWNER}/${REPO_NAME}"
INSTALL_DIR="${CLIFF_HOME:-$HOME/cliff}"
VERSION="${CLIFF_VERSION:-latest}"
NON_INTERACTIVE="${CLIFF_NON_INTERACTIVE:-}"

# ---- pretty output ----------------------------------------------------------

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

say()  { printf '%s%s%s\n' "${BLUE}" "$1" "${RESET}"; }
ok()   { printf '%s✓%s %s\n' "${GREEN}" "${RESET}" "$1"; }
warn() { printf '%s!%s %s\n' "${YELLOW}" "${RESET}" "$1" >&2; }
fail() { printf '%s✗%s %s\n' "${RED}" "${RESET}" "$1" >&2; exit 1; }

# ---- preflight --------------------------------------------------------------

say "Cliff installer"
printf '%sInstall dir:%s %s\n' "${DIM}" "${RESET}" "${INSTALL_DIR}"
printf '%sVersion:%s     %s\n' "${DIM}" "${RESET}" "${VERSION}"
echo

if ! command -v docker >/dev/null 2>&1; then
  fail "docker not found. Install Docker 24+ from https://docs.docker.com/engine/install/ and re-run."
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "docker compose plugin not found. Install Docker Compose v2 (bundled with Docker Desktop, or 'docker-compose-plugin' on Linux)."
fi

if ! docker info >/dev/null 2>&1; then
  fail "docker daemon is not running or current user can't reach it. Start Docker Desktop, or add your user to the 'docker' group on Linux."
fi

ok "Docker available ($(docker --version | cut -d' ' -f3 | tr -d ','))"

# ---- write install dir ------------------------------------------------------

mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

# Pin to a specific release tag if requested; default to 'latest'.
if [ "${VERSION}" = "latest" ]; then
  RELEASE_BASE="${GH_REPO}/releases/latest/download"
else
  RELEASE_BASE="${GH_REPO}/releases/download/v${VERSION}"
fi

download() {
  url="$1"
  dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${url}" -o "${dest}"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "${url}" -O "${dest}"
  else
    fail "Neither curl nor wget found. Install one and re-run."
  fi
}

# Install the agent-facing CLI (`cliff`) into ~/.local/bin if the release
# ships it. The CLI is a normal Unix binary going to a normal Unix location,
# so this is an extension of `curl ... | sh` consent — same as rustup, nvm,
# uv, etc. install.
#
# We deliberately do NOT touch ~/.claude/. The /secure-repo skill is
# distributed via the official Claude Code plugin marketplace mechanism and
# requires explicit user opt-in via `/plugin marketplace add` + `/plugin
# install`. We just print the command at the end (see end of script).
install_agent_cli() {
  cli_archive="cliff-cli.tar.gz"
  cli_url="${RELEASE_BASE}/${cli_archive}"
  bin_dir="${HOME}/.local/bin"

  if ! command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  if ! download "${cli_url}" "/tmp/${cli_archive}" 2>/dev/null; then
    return 0
  fi
  venv_dir="${HOME}/.cliff/cli-venv"
  python3 -m venv "${venv_dir}" >/dev/null 2>&1 || true
  "${venv_dir}/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
  if "${venv_dir}/bin/pip" install --quiet "/tmp/${cli_archive}" >/dev/null 2>&1; then
    mkdir -p "${bin_dir}"
    ln -sf "${venv_dir}/bin/cliff" "${bin_dir}/cliff"
    ok "Installed cliff CLI to ${bin_dir}/cliff"
    case ":${PATH}:" in
      *":${bin_dir}:"*) : ;;
      *) warn "${bin_dir} is not in your PATH — add it to use the 'cliff' command." ;;
    esac
  fi
  rm -f "/tmp/${cli_archive}"
}

say "Downloading docker-compose.yml"
download "${RELEASE_BASE}/docker-compose.yml" "docker-compose.yml" \
  || fail "Failed to download docker-compose.yml from ${RELEASE_BASE}"
ok "docker-compose.yml in place"

# ---- .env -------------------------------------------------------------------

if [ -f .env ]; then
  ok ".env already exists — preserving"
  ENV_EXISTS=1
else
  ENV_EXISTS=0
  say "Generating .env"
  download "${RELEASE_BASE}/.env.example" ".env.example" 2>/dev/null \
    || cat > .env.example <<'EOF'
# Cliff runtime config
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
CLIFF_CREDENTIAL_KEY=
EOF
  cp .env.example .env

  # Generate a fresh credential vault key.
  if command -v openssl >/dev/null 2>&1; then
    KEY=$(openssl rand -base64 32)
  elif command -v python3 >/dev/null 2>&1; then
    KEY=$(python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')
  else
    warn "Neither openssl nor python3 available — skipping CLIFF_CREDENTIAL_KEY generation."
    KEY=""
  fi
  if [ -n "${KEY}" ]; then
    # Replace CLIFF_CREDENTIAL_KEY=... with the generated value.
    # Use awk for portable in-place edit (sed -i is not POSIX).
    awk -v k="${KEY}" '/^CLIFF_CREDENTIAL_KEY=/ {print "CLIFF_CREDENTIAL_KEY=" k; next} {print}' \
      .env > .env.tmp && mv .env.tmp .env
    ok "CLIFF_CREDENTIAL_KEY generated"
  fi
fi

# ---- API key ---------------------------------------------------------------

key_set_in_env() {
  # Returns 0 if either key is set in the .env file (non-empty value).
  awk -F= '
    /^ANTHROPIC_API_KEY=/ { if (length($2) > 0) found=1 }
    /^OPENAI_API_KEY=/    { if (length($2) > 0) found=1 }
    END { exit found ? 0 : 1 }
  ' .env
}

if [ "${ENV_EXISTS}" -eq 0 ]; then
  # Pull from environment if available
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    awk -v k="${ANTHROPIC_API_KEY}" '/^ANTHROPIC_API_KEY=/ {print "ANTHROPIC_API_KEY=" k; next} {print}' \
      .env > .env.tmp && mv .env.tmp .env
    ok "ANTHROPIC_API_KEY copied from environment"
  elif [ -n "${OPENAI_API_KEY:-}" ]; then
    awk -v k="${OPENAI_API_KEY}" '/^OPENAI_API_KEY=/ {print "OPENAI_API_KEY=" k; next} {print}' \
      .env > .env.tmp && mv .env.tmp .env
    ok "OPENAI_API_KEY copied from environment"
  elif [ -z "${NON_INTERACTIVE}" ] && [ -t 0 ]; then
    echo
    echo "Cliff needs an LLM API key. Paste your Anthropic or OpenAI key:"
    printf '  %sANTHROPIC_API_KEY%s (preferred, leave blank to enter OPENAI_API_KEY): ' "${BOLD}" "${RESET}"
    read -r INPUT_KEY
    if [ -n "${INPUT_KEY}" ]; then
      awk -v k="${INPUT_KEY}" '/^ANTHROPIC_API_KEY=/ {print "ANTHROPIC_API_KEY=" k; next} {print}' \
        .env > .env.tmp && mv .env.tmp .env
    else
      printf '  %sOPENAI_API_KEY%s: ' "${BOLD}" "${RESET}"
      read -r INPUT_KEY
      if [ -n "${INPUT_KEY}" ]; then
        awk -v k="${INPUT_KEY}" '/^OPENAI_API_KEY=/ {print "OPENAI_API_KEY=" k; next} {print}' \
          .env > .env.tmp && mv .env.tmp .env
      fi
    fi
  fi
fi

if ! key_set_in_env; then
  warn "No LLM API key set in .env. The container will start but agent calls will fail."
  warn "Edit ${INSTALL_DIR}/.env and set ANTHROPIC_API_KEY or OPENAI_API_KEY before using Cliff."
fi

# ---- pull and start --------------------------------------------------------

# If a non-default version was requested, pin docker-compose.yml to it.
if [ "${VERSION}" != "latest" ]; then
  export CLIFF_VERSION="${VERSION}"
fi

say "Pulling image"
docker compose pull >/dev/null 2>&1 || warn "Image pull reported a problem; continuing in case the image is already local."

say "Starting Cliff"
docker compose up -d
ok "Container started"

# ---- wait for /health ------------------------------------------------------

# Try a few candidate ports in case CLIFF_APP_PORT is set in .env.
PORT=$(grep -E '^CLIFF_APP_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || true)
PORT="${PORT:-8000}"
URL="http://localhost:${PORT}/health"

say "Waiting for ${URL}"
ATTEMPT=0
MAX_ATTEMPTS=60   # ~60s
while [ "${ATTEMPT}" -lt "${MAX_ATTEMPTS}" ]; do
  if curl -fsS "${URL}" >/dev/null 2>&1; then
    echo
    ok "Cliff is healthy"

    # ---- agent CLI + Claude Code skill -----------------------------------
    # Best-effort: if the release doesn't carry these assets yet, skip
    # quietly. The user can still drive Cliff from the web UI.
    install_agent_cli || true

    echo
    printf '  %sOpen %shttp://localhost:%s%s%s in your browser.\n' \
      "${BOLD}" "${BLUE}" "${PORT}" "${RESET}" "${RESET}"
    echo
    printf '  %sUsing Claude Code?%s Install the /secure-repo plugin (one-time):\n' \
      "${BOLD}" "${RESET}"
    printf '    %s/plugin marketplace add cliff-security/cliff%s\n' "${DIM}" "${RESET}"
    printf '    %s/plugin install secure-repo@cliff%s\n' "${DIM}" "${RESET}"
    printf '  Then ask Claude: %s"secure this repo with Cliff"%s\n' "${BOLD}" "${RESET}"
    echo
    printf '  %sLogs:%s    docker compose -f %s/docker-compose.yml logs -f\n' \
      "${DIM}" "${RESET}" "${INSTALL_DIR}"
    printf '  %sStop:%s    docker compose -f %s/docker-compose.yml down\n' \
      "${DIM}" "${RESET}" "${INSTALL_DIR}"
    printf '  %sUpgrade:%s re-run this installer\n' "${DIM}" "${RESET}"
    exit 0
  fi
  sleep 1
  ATTEMPT=$((ATTEMPT + 1))
done

warn "Timed out waiting for ${URL}."
warn "The container is up but didn't become healthy in 60s. Check logs:"
warn "  docker compose -f ${INSTALL_DIR}/docker-compose.yml logs"
exit 1
