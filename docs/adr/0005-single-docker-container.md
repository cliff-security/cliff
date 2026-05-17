# ADR-0005: Single Docker Container Deployment

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff targets self-hosted community users who want a simple install experience. The MVP should start with one command.

The app has multiple internal components:

- FastAPI backend (Python)
- Built frontend (static files)
- OpenCode server (Go binary)
- SQLite database (file)

## Decision

Package everything into a **single Docker container** exposing port **8000**.

Internal layout:

- FastAPI serves the API and built frontend static files
- OpenCode runs as a managed subprocess on an internal-only port (default 4096)
- SQLite file lives in a mounted volume (`/data`)
- A process manager (supervisord or similar) manages FastAPI + OpenCode processes

## Consequences

- **Easier:** `docker run -p 8000:8000 cliff` is the entire install process.
- **Easier:** One image to build, push, and version. Simple upgrade path.
- **Harder:** Larger image (Python + Go + Node build stage). Multi-stage build mitigates this.
- **Harder:** Single container means no horizontal scaling. Acceptable for single-user MVP.
- **Harder:** If OpenCode crashes, the process manager must restart it. Needs health monitoring.
