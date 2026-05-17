# Development Setup

## Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm
- Docker (for containerized runs, optional for dev)

## Clone

```bash
git clone https://github.com/galanko/Cliff.git
cd Cliff
```

## Quick Start (both servers)

```bash
scripts/dev.sh
```

This starts FastAPI on port 8000 (which manages OpenCode on port 4096 internally) and Vite on port 5173.

## Backend Only

```bash
cd backend
uv sync --extra dev    # install dependencies including test tools
uv run uvicorn cliff.main:app --reload --port 8000
```

## Frontend Only

Needs the backend running for API proxy.

```bash
cd frontend
npm install
npm run dev            # starts Vite dev server on port 5173
```

## OpenCode Binary

OpenCode is auto-downloaded on first backend startup. To install manually:

```bash
scripts/install-opencode.sh
# Or: brew install opencode
# Or: npm i -g opencode-ai
```

The pinned version is in `.opencode-version`.

## Running Tests

```bash
# Backend tests (28 tests, ~0.2s)
cd backend && uv run pytest -v

# Lint check
cd backend && uv run ruff check cliff/ tests/

# Frontend (coming in Phase 2)
cd frontend && npm test
```

## Docker (full stack)

```bash
docker compose up --build
# App available at http://localhost:8000
```
