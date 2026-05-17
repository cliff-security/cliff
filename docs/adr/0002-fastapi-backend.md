# ADR-0002: FastAPI for the Backend

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff needs a product backend to manage findings, workspaces, agent runs, history, settings, and adapter integrations. While OpenCode provides an LLM/runtime server, it does not handle product domain state.

We need a framework that supports:

- REST API with automatic OpenAPI documentation
- Async request handling (agent runs can be long-lived)
- WebSocket or SSE support for streaming agent results to the browser
- Strong typing and validation
- Python ecosystem (aligns with security tooling and team expertise)

## Decision

Use **FastAPI** with uvicorn as the product backend.

- Pydantic models for request/response validation and domain entities
- Async endpoints for agent orchestration and streaming
- FastAPI serves both the API and the built frontend static files in production
- Python 3.11+ required

## Consequences

- **Easier:** Automatic OpenAPI docs, strong typing, and async support out of the box.
- **Easier:** Python ecosystem has excellent security tooling libraries.
- **Easier:** Pydantic models serve double duty as validation and documentation.
- **Harder:** Two languages in the stack (Python backend + TypeScript frontend). Acceptable tradeoff.
- **Harder:** FastAPI is single-process by default; for MVP single-user this is fine.
