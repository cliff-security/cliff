#!/usr/bin/env bash
# Smoke test for the native installer. Runs in CI and locally.
#
# Builds the tarball with a stub frontend, installs it into a scratch
# CLIFF_HOME, asserts `cliffsec doctor` is healthy, starts the daemon
# detached on a non-default port, hits /health, then stops it.
#
# Designed to be safe to run on a developer's box: it never touches the
# real ~/.cliff/, never writes to ~/.local/bin (we add the cli-venv to
# PATH manually instead), and cleans up on exit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

TEST_HOME="$(mktemp -d -t cliff-smoke-XXXXXXXX)"
TEST_PORT="${TEST_PORT:-8765}"
TARBALL=""

cleanup() {
  rc=$?
  set +e
  # On failure, dump the daemon log before tearing down so the operator
  # (or CI) sees why it didn't come up healthy.
  if [[ "${rc}" != "0" ]] && [[ -d "${TEST_HOME}/data/logs" ]]; then
    echo
    echo "===== detached daemon log ====="
    for log in "${TEST_HOME}"/data/logs/cliff-*.log; do
      [[ -f "${log}" ]] || continue
      echo "--- ${log} ---"
      cat "${log}"
    done
    echo "==============================="
  fi
  # If the daemon is still up, kill it.
  if [[ -f "${TEST_HOME}/run/cliff.pid" ]]; then
    pid="$(cat "${TEST_HOME}/run/cliff.pid")"
    kill "${pid}" 2>/dev/null || true
    sleep 1
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -rf "${TEST_HOME}"
  rm -rf "${REPO_ROOT}/dist"
  exit $rc
}
trap cleanup EXIT

# ---- 1. ensure a frontend/dist exists --------------------------------------
mkdir -p frontend/dist
if [[ ! -s frontend/dist/index.html ]]; then
  cat > frontend/dist/index.html <<'EOF'
<!doctype html><html><head><title>Cliff smoke</title></head>
<body>Cliff smoke build — replace with `npm run build`.</body></html>
EOF
fi

# ---- 2. build tarball ------------------------------------------------------
echo "==> building tarball"
SKIP_FRONTEND_BUILD=1 scripts/build-tarball.sh >/dev/null
TARBALL="$(ls -1 dist/cliffsec-*.tar.gz | head -1)"
[[ -f "${TARBALL}" ]] || { echo "FAIL: no tarball produced"; exit 1; }

# Layout sanity: every file the installer relies on must be in the tarball.
# We list the archive once into a variable rather than piping into `grep -q`
# in a loop — `grep -q` exits early, which under `set -o pipefail` causes
# GNU tar to report a SIGPIPE write error and fail the pipeline.
tarball_listing="$(tar -tzf "${TARBALL}")"
for required in \
    backend/pyproject.toml \
    backend/cliff/main.py \
    frontend/dist/index.html \
    cli/pyproject.toml \
    cli/cliff_cli/cli.py \
    cli/cliff_cli/daemon.py \
    scripts/install-scanners.sh \
    .scanner-versions \
    VERSION ; do
  if ! grep -qE "(^|/)${required}\$" <<<"${tarball_listing}"; then
    echo "FAIL: ${required} missing from tarball"
    exit 1
  fi
done
echo "  tarball layout OK"

# ---- 3. install ------------------------------------------------------------
echo "==> installing into ${TEST_HOME}"
# We point install-local.sh at the local tarball and use CLIFF_HOME.
# We also bypass the ~/.local/bin/cliffsec symlink step so the developer's
# real CLI is never disturbed.
CLIFF_HOME="${TEST_HOME}" \
CLIFF_LOCAL_TARBALL="${REPO_ROOT}/${TARBALL}" \
HOME="${TEST_HOME}" \
  sh scripts/install-local.sh >/dev/null

CLI="${TEST_HOME}/cli-venv/bin/cliffsec"
[[ -x "${CLI}" ]] || { echo "FAIL: cli-venv missing at ${CLI}"; exit 1; }

# ---- 4. doctor -------------------------------------------------------------
echo "==> cliffsec doctor --json"
DOCTOR_OUT="$(CLIFF_HOME="${TEST_HOME}" "${CLI}" doctor --json || true)"
# Parse via the cli venv's python (guaranteed present after install) — system
# python3 is missing on minimal containers we test in.
echo "${DOCTOR_OUT}" | "${TEST_HOME}/cli-venv/bin/python" -c "
import json, sys
data = json.loads(sys.stdin.read())
fails = data.get('failing', [])
# Tolerate port.4096 if another workflow holds it.
fails = [f for f in fails if f != 'port.4096']
if fails:
    print('FAIL: doctor failing:', fails)
    sys.exit(1)
print('  doctor: clean (warnings:', data.get('warnings', []), ')')
"

# ---- 5. start --detach + health + stop ------------------------------------
echo "==> cliffsec start --detach --port ${TEST_PORT}"
CLIFF_HOME="${TEST_HOME}" "${CLI}" start --detach --port "${TEST_PORT}" >/dev/null

# /health should respond within ~5s of start returning (start already
# waited for it, but we re-check to be sure the process is healthy).
for _ in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:${TEST_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -fsS "http://127.0.0.1:${TEST_PORT}/health" >/dev/null; then
  echo "FAIL: /health did not respond"
  exit 1
fi
echo "  /health: ok"

echo "==> cliffsec stop"
CLIFF_HOME="${TEST_HOME}" "${CLI}" stop >/dev/null

# Confirm the port is released.
sleep 1
if curl -fsS "http://127.0.0.1:${TEST_PORT}/health" >/dev/null 2>&1; then
  echo "FAIL: daemon still responding after stop"
  exit 1
fi

# ---- 6. orphan-cleanup scenario --------------------------------------------
# Simulates a hard crash: start the daemon, SIGKILL the parent so the lifespan
# cleanup never runs, then run `cliffsec stop` and verify the OpenCode singleton
# port (4096) is reclaimed. The CLI must sweep for orphans, not just trust
# the pidfile.
#
# The previous step's stop may have left 4096 in TIME_WAIT. Wait up to 60s for
# the port to free up before starting; skip the scenario if it never frees
# (someone else's opencode is squatting it on this dev box).
echo "==> orphan cleanup scenario"
for _ in $(seq 1 60); do
  "${TEST_HOME}/cli-venv/bin/python" -c "
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', 4096)); s.close()
except OSError:
    sys.exit(1)
" && break
  sleep 1
done

if "${TEST_HOME}/cli-venv/bin/python" -c "
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', 4096))
    s.close()
except OSError:
    sys.exit(2)
" ; then
  CLIFF_HOME="${TEST_HOME}" "${CLI}" start --detach --port "${TEST_PORT}" >/dev/null
  parent_pid="$(cat "${TEST_HOME}/run/cliff.pid")"
  # Give the backend lifespan a moment to spawn the OpenCode singleton.
  sleep 3
  # Hard-kill the parent so the lifespan cleanup never runs.
  kill -9 "${parent_pid}" 2>/dev/null || true
  sleep 1

  CLIFF_HOME="${TEST_HOME}" "${CLI}" stop >/dev/null 2>&1 || true
  sleep 1

  if "${TEST_HOME}/cli-venv/bin/python" -c "
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', 4096))
except OSError:
    sys.exit(1)
" ; then
    echo "  orphan port 4096 reclaimed"
  else
    echo "FAIL: orphan opencode port 4096 still bound after stop"
    exit 1
  fi
else
  echo "  skipped (port 4096 in use by another process before scenario)"
fi

# ---- 7. custom-port scenario -----------------------------------------------
# Persist a different app port via `config set`, restart, and verify the
# daemon comes up on it. Catches port-pass-through regressions.
echo "==> custom port via config set"
ALT_PORT=$((TEST_PORT + 1))
CLIFF_HOME="${TEST_HOME}" "${CLI}" config set "CLIFF_APP_PORT=${ALT_PORT}" >/dev/null
CLIFF_HOME="${TEST_HOME}" "${CLI}" start --detach >/dev/null

for _ in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:${ALT_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -fsS "http://127.0.0.1:${ALT_PORT}/health" >/dev/null; then
  echo "FAIL: /health did not respond on alt port ${ALT_PORT}"
  exit 1
fi
echo "  /health on ${ALT_PORT}: ok"

CLIFF_HOME="${TEST_HOME}" "${CLI}" stop >/dev/null

echo
echo "OK — installer smoke test passed."
