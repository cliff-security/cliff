-- 015_assessment_failure_detail.sql
-- Persist *why* an assessment ended in `failed`.
--
-- Before this migration, the background task caught any exception, logged it
-- to stdout, and flipped status='failed' — but the failure reason was never
-- surfaced to the API or the UI. A user whose clone broke had to spin up a
-- second tool to debug what went wrong.
--
-- All four columns are nullable so existing rows (and rows that complete
-- successfully) stay valid; the background runner populates them only on the
-- failure path.
--
-- error_kind     — short machine code: clone_failed | scanner_failed |
--                  timeout | internal_error | interrupted
-- error_message  — friendly one-liner the UI renders as the headline
-- error_details  — raw stderr / exception text (clone.py already redacts
--                  the GitHub PAT before raising)
-- failed_step    — engine step at the moment of failure: clone | detect |
--                  trivy_vuln | trivy_secret | semgrep | posture |
--                  descriptions | persist | unknown
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE assessment ADD COLUMN error_kind TEXT;
ALTER TABLE assessment ADD COLUMN error_message TEXT;
ALTER TABLE assessment ADD COLUMN error_details TEXT;
ALTER TABLE assessment ADD COLUMN failed_step TEXT;

COMMIT;
