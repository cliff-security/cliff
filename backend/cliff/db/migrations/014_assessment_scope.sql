-- 014_assessment_scope.sql
-- Capture per-assessment scope + counters for the new Dashboard "Last assessment"
-- panel (IMPL-0009).
--
-- The redesigned panel surfaces scope context the engine already knows but
-- never persisted: which commit + branch were scanned, how many files Semgrep
-- walked, and how many dependencies the parser registry resolved. All four
-- columns are nullable so legacy rows and in-flight assessments stay valid;
-- the engine populates them at the end of each run.
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE assessment ADD COLUMN commit_sha TEXT;
ALTER TABLE assessment ADD COLUMN branch TEXT;
ALTER TABLE assessment ADD COLUMN scanned_files INTEGER;
ALTER TABLE assessment ADD COLUMN scanned_deps INTEGER;

COMMIT;
