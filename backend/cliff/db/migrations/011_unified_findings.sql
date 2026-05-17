-- 011_unified_findings.sql
-- ADR-0027 (unified findings model) + ADR-0033 (pre-alpha destructive migrations).
--
-- Authorized destructive scope (ADR-0033 §1):
--   DROP TABLE finding         -- regeneratable by re-running an assessment
--   DROP TABLE posture_check   -- regeneratable by re-running an assessment
--
-- Tables explicitly preserved (NOT touched here):
--   assessment, completion, app_setting, integration_config, credential,
--   repo_settings, workspace, message, agent_run, ingest_job, audit_log
--
-- After upgrade, the operator must trigger a re-assessment to repopulate
-- findings and posture rows. The release notes for the build that ships
-- this migration repeat this list.
--
-- ADR-0027 §4 originally specified that passing posture checks NOT be
-- persisted as finding rows. PR-B consciously overrides that: per CEO
-- direction (2026-04-26), the unified ``finding`` table holds every
-- finding the user has ever had — pass + fail + advisory + closed —
-- so the Findings page (when expanded post-v0.2 to filter on type)
-- has a complete picture and the dashboard's posture pass count maps
-- directly to a row count rather than to ``criteria_snapshot``.
--
-- This migration's destructive license expires at v0.1.0-alpha (ADR-0033 §3).
-- Any future change to ``finding`` after that tag must be additive.

BEGIN;

-- 1. Drop the legacy tables. Order matters: indexes first, then tables.
DROP INDEX IF EXISTS idx_finding_status;
DROP INDEX IF EXISTS idx_finding_source;
DROP TABLE IF EXISTS finding;

DROP INDEX IF EXISTS idx_posture_check_assessment;
DROP TABLE IF EXISTS posture_check;

-- 2. Recreate the unified finding table per ADR-0027.
CREATE TABLE finding (
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
    updated_at          TEXT NOT NULL
);

-- 3. Indexes — UNIQUE on (source_type, source_id) is the UPSERT target.
CREATE UNIQUE INDEX uq_finding_source       ON finding(source_type, source_id);
CREATE        INDEX idx_finding_type        ON finding(type);
CREATE        INDEX idx_finding_status      ON finding(status);
CREATE        INDEX idx_finding_assessment  ON finding(assessment_id, type);

COMMIT;
