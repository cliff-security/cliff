# ADR-0004: SQLite for Persistence

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff needs persistent storage for findings, workspaces, messages, agent runs, sidebar state, ticket links, settings, and integration configs.

Options considered:

- **PostgreSQL:** Powerful but adds operational complexity (separate service, connection management). Overkill for single-user self-hosted app.
- **Plain files (JSON/YAML):** Simple but lacks structured querying, relational integrity, and concurrent access safety.
- **SQLite:** Zero-configuration, single-file database. Supports structured queries, migrations, and atomic writes.

## Decision

Use **SQLite** as the primary database.

- Single file stored in a mounted volume (`data/cliff.db`)
- WAL mode enabled for read concurrency
- Migrations managed via numbered SQL scripts
- Accessed via Python's `aiosqlite` for async compatibility with FastAPI
- Schema designed to be migration-ready for a future Postgres upgrade path

## Consequences

- **Easier:** Zero operational overhead. Backup = copy one file. No external services to manage.
- **Easier:** Perfect fit for single-user, single-container deployment model.
- **Harder:** No concurrent write scaling. Acceptable for single-user MVP.
- **Harder:** Some SQL features (e.g., JSON functions) differ from Postgres. Keep queries portable where practical.
