-- 024_triage_contract.sql
-- ADR-0051 / IMPL-0024 M1 — the triage contract. Forward-only (ADR-0033).
--
-- (1) Rebuild the finding.exception_reason CHECK to add the new
--     'unexploitable' reason (PRD-0008: "real advisory, not reachable here").
--     SQLite cannot ALTER a CHECK constraint, so the canonical fix is a
--     table rebuild. Foreign keys MUST be disabled for the rebuild: dropping
--     the old `finding` table with FK enforcement on would cascade through
--     `workspace.finding_id` and delete child workspace rows.
--
-- (2) Add a nullable JSON `triage` column to sidebar_state so the
--     SidebarState.triage section (TriageOutput) can persist. The sidebar
--     store is columnar (one JSON column per section, like `pull_request` in
--     migration 007), so the additive section needs a column — IMPL-0024
--     §3.1's "no migration needed" note is corrected here.

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE finding_new (
    id                  TEXT PRIMARY KEY,
    source_type         TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    type                TEXT NOT NULL DEFAULT 'dependency',
    grade_impact        TEXT NOT NULL DEFAULT 'counts',
    category            TEXT,
    assessment_id       TEXT REFERENCES assessment(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    description         TEXT,
    plain_description   TEXT,
    raw_severity        TEXT,
    normalized_priority TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    likely_owner        TEXT,
    why_this_matters    TEXT,
    asset_id            TEXT,
    asset_label         TEXT,
    raw_payload         TEXT,
    pr_url              TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    exception_reason    TEXT
        CHECK (
            exception_reason IS NULL
            OR exception_reason IN (
                'false_positive',
                'accepted_risk',
                'wont_fix',
                'deferred',
                'unexploitable'
            )
        ),
    exception_note      TEXT
);

INSERT INTO finding_new (
    id, source_type, source_id, type, grade_impact, category, assessment_id,
    title, description, plain_description, raw_severity, normalized_priority,
    status, likely_owner, why_this_matters, asset_id, asset_label, raw_payload,
    pr_url, created_at, updated_at, exception_reason, exception_note
)
SELECT
    id, source_type, source_id, type, grade_impact, category, assessment_id,
    title, description, plain_description, raw_severity, normalized_priority,
    status, likely_owner, why_this_matters, asset_id, asset_label, raw_payload,
    pr_url, created_at, updated_at, exception_reason, exception_note
FROM finding;

DROP TABLE finding;
ALTER TABLE finding_new RENAME TO finding;

-- Recreate the indexes the original `finding` table carried.
CREATE UNIQUE INDEX uq_finding_source     ON finding(source_type, source_id);
CREATE INDEX        idx_finding_type       ON finding(type);
CREATE INDEX        idx_finding_status     ON finding(status);
CREATE INDEX        idx_finding_assessment ON finding(assessment_id, type);

ALTER TABLE sidebar_state ADD COLUMN triage TEXT;  -- JSON

COMMIT;

PRAGMA foreign_keys = ON;
