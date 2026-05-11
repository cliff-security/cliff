#!/usr/bin/env bash
set -euo pipefail

# Start OpenSec development servers.
# FastAPI (port 8000) manages the OpenCode subprocess internally.
# Vite (port 5173) proxies API calls to FastAPI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Starting OpenSec dev environment..."

# Ensure dependencies are installed
if [[ ! -d "$REPO_ROOT/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$REPO_ROOT/frontend" && npm install)
fi

# Start backend (FastAPI + OpenCode)
#
# ``--reload-dir opensec`` + ``--reload-exclude data/*`` keeps the
# auto-reloader from waking up on every assessment. The engine
# clones each target repo into ``data/clones/`` (see
# ``opensec.api._engine_dep``) and a clone of a Python repo lands
# dozens of ``.py`` files there mid-run — without this guard the
# default whole-tree watcher restarts the server and every
# assessment fails with "Assessment was interrupted (the server
# restarted)".
echo "Starting backend on :8000..."
(cd "$REPO_ROOT/backend" && uv run uvicorn opensec.main:app \
   --port 8000 \
   --reload \
   --reload-dir opensec \
   --reload-exclude 'data/*') &
BACKEND_PID=$!

# Start frontend (Vite)
echo "Starting frontend on :5173..."
(cd "$REPO_ROOT/frontend" && npm run dev) &
FRONTEND_PID=$!

# Cleanup on exit
cleanup() {
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  wait
}
trap cleanup EXIT INT TERM

echo ""
echo "OpenSec dev servers running:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""

wait
