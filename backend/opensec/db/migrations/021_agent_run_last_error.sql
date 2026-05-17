-- 021_agent_run_last_error.sql
-- EF-B17 — Add a canonical `last_error` column on `agent_run`.
--
-- Before this change, the error text from a non-success run lived only inside
-- `evidence_json` (a TEXT-encoded JSON blob), which made it invisible to the
-- Dashboard / AgentRunCard and impossible to query without `json_extract`.
-- Acceptance criterion #3 of EF-B17 requires `last_error` to be populated for
-- every run that ends non-success — that needs a dedicated column.
--
-- `status` is already declared `TEXT NOT NULL DEFAULT 'queued'` in
-- `001_initial_schema.sql` with no CHECK constraint, so the new
-- `'rate_limited'` literal needs no schema change here.

ALTER TABLE agent_run ADD COLUMN last_error TEXT;
