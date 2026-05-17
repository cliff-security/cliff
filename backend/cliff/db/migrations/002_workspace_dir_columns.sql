-- 002_workspace_dir_columns.sql
-- Add workspace directory tracking columns for ADR-0014 Layer 2.
-- workspace_dir: filesystem path to the isolated workspace directory.
-- context_version: bumped on each context update (agent run output written).

ALTER TABLE workspace ADD COLUMN workspace_dir TEXT;
ALTER TABLE workspace ADD COLUMN context_version INTEGER NOT NULL DEFAULT 0;
