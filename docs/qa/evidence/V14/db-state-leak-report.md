# V14 — DB-level workspace state-leak test

**Wave 0 task.** Closes the schema-level boundary on the workspace-isolation
promise. ADR-0014 covers *process* isolation; V14 covers *data* isolation.

- **Date:** 2026-05-14
- **Test file:** `backend/tests/integration/test_sidebar_state_isolation.py`
- **Verdict:** PASS — all 8 tests green. No leak found. v0.1.0-alpha not blocked.

## What this verifies

Two workspaces opened against two different findings cannot read each other's
rows in `sidebar_state`, `message`, `agent_run`, or `ticket_link`. Every
production read path scopes by `workspace_id`.

## Test results

| Test | Table | Result |
|------|-------|--------|
| `test_two_workspaces_cannot_see_each_others_sidebar_state` | `sidebar_state` | PASS |
| `test_message_isolation` | `message` | PASS |
| `test_agent_run_isolation` | `agent_run` | PASS |
| `test_ticket_link_isolation` | `ticket_link` | PASS |
| `test_sidebar_query_without_workspace_id_raises` | `sidebar_state` (belt-and-suspenders) | PASS |
| `test_message_query_without_workspace_id_raises` | `message` (belt-and-suspenders) | PASS |
| `test_agent_run_query_without_workspace_id_raises` | `agent_run` (belt-and-suspenders) | PASS |
| `test_ticket_link_query_without_workspace_id_raises` | `ticket_link` (belt-and-suspenders) | PASS |

```
8 passed in 0.29s
```

## Tables exercised

- **`sidebar_state`** — `workspace_id` is the PRIMARY KEY (`REFERENCES workspace(id) ON DELETE CASCADE`). Read via `repo_sidebar.get_sidebar(db, workspace_id)`; write via `upsert_sidebar`. Scoped by construction.
- **`message`** — `workspace_id` is `NOT NULL REFERENCES workspace(id) ON DELETE CASCADE`, indexed (`idx_message_workspace`). Read via `repo_message.list_messages(db, workspace_id, …)` — `WHERE workspace_id = ?`.
- **`agent_run`** — `workspace_id` is `NOT NULL REFERENCES workspace(id) ON DELETE CASCADE`, indexed (`idx_agent_run_workspace`). Read via `repo_agent_run.list_agent_runs(db, workspace_id, …)` — `WHERE workspace_id = ?`.
- **`ticket_link`** — `workspace_id` is `NOT NULL REFERENCES workspace(id) ON DELETE CASCADE`, indexed (`idx_ticket_link_workspace`). See note below.

## Query paths found to need a `workspace_id` scope they didn't have

None. All three tables with a repository layer (`sidebar_state`, `message`,
`agent_run`) already scope every list/get query by `workspace_id`, and the
helper signatures make `workspace_id` a positional-required argument — a
forgetful caller fails with `TypeError` rather than silently reading global
data (verified by the four belt-and-suspenders tests).

## Note: `ticket_link` has no repository layer

`ticket_link` exists in the schema (migration `001_initial_schema.sql`) but has
**no repository functions and no production read/write path** anywhere in
`backend/opensec/`. There is therefore nothing to leak today.

The V14 suite still exercises the table at the schema level: rows are inserted
via raw SQL and read back through a local `_list_ticket_links` helper that makes
`workspace_id` a **required keyword-only argument**, mirroring the repo-layer
convention. This locks in the isolation guarantee — and the belt-and-suspenders
expectation — for the day a real `repo_ticket_link` is added. **Action for
whoever builds that repo:** keep `workspace_id` required on every read helper.

## CI integration

- New marker `integration` registered in `backend/pyproject.toml` (`[tool.pytest.ini_options]`).
- Tests live in `backend/tests/integration/` with a local `conftest.py` providing the in-memory-DB `db` fixture (all migrations applied, foreign keys on).
- No external dependencies — no OpenCode binary, no LLM key. Runs on every CI build under the default `pytest` invocation; confirmed collected under `-m 'not e2e'` (8/8). No `-m e2e` opt-in needed.

## Action if a test fails

P0 by definition — a workspace data leak in a security tool is a trust-collapse
bug. Block v0.1.0-alpha, fix in a focused engineering session, re-run V14, then
resume the campaign.
