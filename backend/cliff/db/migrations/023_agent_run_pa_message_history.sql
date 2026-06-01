-- 023_agent_run_pa_message_history.sql
-- Durable Pydantic AI message history for resuming a paused executor run.
--
-- ADR-0047 / IMPL-0022 PR #2 moves the remediation_executor onto Pydantic
-- AI. When the agent calls a gated tool (e.g. ``rm -rf``) the run pauses
-- with a ``DeferredToolRequests`` output; the pending request is stored in
-- the existing ``permission_request`` column (migration 022). To RESUME
-- after the user approves/denies, PA needs the full conversation up to the
-- pause point fed back via ``agent.run(message_history=...)`` — so we
-- persist ``result.all_messages_json()`` here.
--
-- Storing it in the DB (rather than an in-memory dict or a workspace file)
-- keeps it atomic with the permission marker and survives a daemon
-- restart mid-approval — the same durability guarantee migration 022 gave
-- the marker itself. One nullable TEXT column holding the PA-serialized
-- message list (UTF-8 JSON); NULL for every run that never paused.
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE agent_run
    ADD COLUMN pa_message_history TEXT;

COMMIT;
