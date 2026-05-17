-- 009_alpha_blockers.sql
-- PRD-0004 / ADR-0030 · Unified workspace schema with active-per-check unique index.
--
-- Before: ``workspace`` was finding-shaped — ``finding_id`` NOT NULL, no ``kind``
-- discriminator, and repo-action workspaces (posture fixes) never persisted a
-- DB row. That meant nothing to enforce the "at most one active workspace per
-- posture check" invariant PRD-0004 Story 3 requires.
--
-- After:
--   - ``kind`` column (DEFAULT 'finding_remediation' so existing rows backfill)
--   - ``source_check_name`` column (NULL for finding-remediation rows)
--   - ``finding_id`` becomes nullable (repo-action workspaces have no finding)
--   - Partial unique index ``idx_workspace_active_per_check`` guards the
--     409 path on ``POST /api/posture/fix/{check_name}``
--
-- SQLite does not support ALTER COLUMN for NULL constraints, so the table is
-- rebuilt. The rebuild is wrapped in PRAGMA foreign_keys = OFF so dependent
-- tables (message, agent_run, sidebar_state, ticket_link, validation_result)
-- keep their references; the rename re-binds them by name.

-- Safety net for re-runs after a partial failure: leftover workspace_new would
-- otherwise collide with CREATE TABLE below.
DROP TABLE IF EXISTS workspace_new;

PRAGMA foreign_keys = OFF;

CREATE TABLE workspace_new (
    id                  TEXT PRIMARY KEY,
    finding_id          TEXT REFERENCES finding(id),
    state               TEXT NOT NULL DEFAULT 'open',
    current_focus       TEXT,
    active_plan_version INTEGER,
    linked_ticket_id    TEXT,
    validation_state    TEXT,
    workspace_dir       TEXT,
    context_version     INTEGER NOT NULL DEFAULT 0,
    kind                TEXT NOT NULL DEFAULT 'finding_remediation',
    source_check_name   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

INSERT INTO workspace_new (
    id, finding_id, state, current_focus, active_plan_version,
    linked_ticket_id, validation_state, workspace_dir, context_version,
    kind, source_check_name, created_at, updated_at
)
SELECT
    id, finding_id, state, current_focus, active_plan_version,
    linked_ticket_id, validation_state, workspace_dir, context_version,
    'finding_remediation', NULL, created_at, updated_at
FROM workspace;

DROP TABLE workspace;
ALTER TABLE workspace_new RENAME TO workspace;

CREATE INDEX IF NOT EXISTS idx_workspace_finding ON workspace(finding_id);
CREATE INDEX IF NOT EXISTS idx_workspace_state ON workspace(state);

-- Partial unique index: at most one workspace in a non-terminal state per
-- ``source_check_name``. NULL source_check_name rows (finding-remediation)
-- are excluded by the predicate so they don't participate.
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_active_per_check
    ON workspace(source_check_name)
    WHERE state IN ('pending', 'running')
      AND source_check_name IS NOT NULL;

PRAGMA foreign_keys = ON;
