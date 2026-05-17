# ADR-0010: Monorepo Structure

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff has multiple components: a Python backend, a TypeScript frontend, a Go dependency (OpenCode), Docker packaging, and documentation. We need to decide between a monorepo and multi-repo approach.

## Decision

Use a **single monorepo** with clearly separated top-level directories:

```
Cliff/
  backend/       — FastAPI application (Python)
  frontend/      — React SPA (TypeScript)
  engine/        — OpenCode submodule (Go)
  docker/        — Dockerfile, docker-compose, process manager config
  docs/          — ADRs, architecture, guides
  scripts/       — Build, dev, and seed scripts
  fixtures/      — Mock/demo data for adapters
  tests/         — Cross-stack integration tests
```

Each directory that will contain code has its own README explaining what belongs there.

## Consequences

- **Easier:** Single PR for cross-cutting changes (e.g., new API endpoint + frontend page).
- **Easier:** One CI pipeline. One place for docs. One repo to clone.
- **Easier:** Simpler for contributors to understand the full picture.
- **Harder:** Developers need Python, Node, and Docker toolchains locally. Mitigated by dev setup docs.
- **Harder:** CI must be smart about running only affected checks. Can be addressed with path-based triggers.
