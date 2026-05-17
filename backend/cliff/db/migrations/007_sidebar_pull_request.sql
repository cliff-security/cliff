-- Add pull_request column to sidebar_state for remediation executor PR data.
ALTER TABLE sidebar_state ADD COLUMN pull_request TEXT;  -- JSON
