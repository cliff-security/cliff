-- 010_assessment_v2_dashboard.sql
-- PRD-0003 v0.2 / ADR-0032 — assessment-v2 dashboard payload.
--
-- Three additive columns; no rebuild required because none affect existing
-- queries or constraints. SQLite ALTER TABLE ... ADD COLUMN is safe under
-- concurrent reads.
--
-- 1. assessment.tools_json — JSON-serialized tools[] payload from ADR-0032
--    (Trivy + Semgrep + posture entries with state and result counts).
-- 2. assessment.summary_seen_at — server-side gate for the assessment-complete
--    interstitial (Surface 3 of PRD-0003). NULL means "user hasn't seen it
--    yet"; ``POST /api/assessment/{id}/mark-summary-seen`` flips this once.
-- 3. posture_check.pr_url — when an Cliff generator agent opens a PR that
--    fixes a failing check, this column carries the URL. The dashboard
--    projects a state of 'done' on the wire when this is non-NULL (the
--    architect's read-time projection rule from ADR-0032).
-- 4. posture_check.category — matches the four PostureCheckCategory values
--    from PRD-0003. Optional; the API layer falls back to the CHECK_CATEGORY
--    map in cliff.assessment.posture for rows where this is NULL.

ALTER TABLE assessment ADD COLUMN tools_json TEXT;
ALTER TABLE assessment ADD COLUMN summary_seen_at TEXT;
ALTER TABLE posture_check ADD COLUMN pr_url TEXT;
ALTER TABLE posture_check ADD COLUMN category TEXT;
