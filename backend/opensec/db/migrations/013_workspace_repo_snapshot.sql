-- 013_workspace_repo_snapshot.sql
-- Snapshot the GitHub integration's repo_url onto the workspace at creation.
--
-- Without this column, agents read the live integration_config.config.repo_url
-- on every run. If the user edits that URL while a workspace is open, in-flight
-- workspaces silently switch repos — and a multi-repo PAT happily clones the
-- wrong target. The snapshot pins each workspace to the repo it was opened
-- against; the integration value remains the fallback for pre-migration rows.
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE workspace
    ADD COLUMN repo_url TEXT;

COMMIT;
