-- 022_agent_run_permission_pending.sql
-- Agent-permission approval gate (Approach A — persisted marker).
--
-- The remediation_executor's tool-use classifier (executor._classify_tool_request)
-- escalates destructive-but-conceivable bash commands (rm, git reset --hard,
-- chmod, …) and out-of-workspace edits to the user. Backend-side these are
-- parked in an in-memory ``_PendingApproval`` keyed by agent_run_id, but
-- the issue-derivation function (issue_derivation.derive) is pure and
-- DB-driven — it can't see in-memory state. Without persistence, the row
-- can't be routed into the Review section's "Needs you" bucket and a page
-- reload would lose the prompt entirely.
--
-- Two nullable columns on agent_run:
--   permission_pending      INTEGER 0/1, default 0
--   permission_request      TEXT (JSON), nullable
--
-- Column name is ``permission_request`` (no ``_json`` suffix) so the
-- DB column, the Pydantic field, and the API/FE-facing JSON key all
-- match — no alias plumbing. Other JSON-bearing columns on agent_run
-- (e.g. ``structured_output``) already use this convention.
--
-- The executor writes both when it parks a ``_PendingApproval`` and clears
-- both when the asyncio event resolves (approve / deny / disconnect-auto-
-- deny). ``reconcile_orphaned_agent_runs`` also clears them when it flips
-- an orphaned ``running`` row to ``failed`` on startup, so a backend
-- restart mid-wait can never leave a stale ``awaiting_permission``.
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE agent_run
    ADD COLUMN permission_pending INTEGER NOT NULL DEFAULT 0
        CHECK (permission_pending IN (0, 1));

ALTER TABLE agent_run
    ADD COLUMN permission_request TEXT;

COMMIT;
