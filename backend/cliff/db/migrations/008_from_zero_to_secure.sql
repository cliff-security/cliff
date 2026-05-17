-- 008_from_zero_to_secure.sql
-- EXEC-0002 / IMPL-0002 Milestone A: adds the assessment, posture_check, and
-- completion tables plus plain_description on finding.
--
-- SQLite does not have a native array type; share_actions_used is stored as a
-- JSON text column (matches the pull_request / raw_payload pattern from 007).

-- Plain-language description surfaced from the finding-normalizer agent.
ALTER TABLE finding ADD COLUMN plain_description TEXT;

-- Assessment — one per repo scan.
CREATE TABLE IF NOT EXISTS assessment (
    id                 TEXT PRIMARY KEY,
    repo_url           TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    completed_at       TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',  -- pending | running | complete | failed
    grade              TEXT,                             -- A | B | C | D | F
    criteria_snapshot  TEXT                              -- JSON
);
CREATE INDEX IF NOT EXISTS idx_assessment_repo_url ON assessment(repo_url);
CREATE INDEX IF NOT EXISTS idx_assessment_status ON assessment(status);

-- PostureCheck — one row per (assessment, check) pair.
CREATE TABLE IF NOT EXISTS posture_check (
    id             TEXT PRIMARY KEY,
    assessment_id  TEXT NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
    check_name     TEXT NOT NULL,
    status         TEXT NOT NULL,  -- pass | fail | advisory | unknown
    detail         TEXT,           -- JSON
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posture_check_assessment ON posture_check(assessment_id);

-- Completion — audit row for the ceremony + shareable summary interactions.
CREATE TABLE IF NOT EXISTS completion (
    id                  TEXT PRIMARY KEY,
    assessment_id       TEXT NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
    repo_url            TEXT NOT NULL,
    completed_at        TEXT NOT NULL,
    criteria_snapshot   TEXT NOT NULL,                  -- JSON
    share_actions_used  TEXT NOT NULL DEFAULT '[]'      -- JSON array of action strings
);
CREATE INDEX IF NOT EXISTS idx_completion_assessment ON completion(assessment_id);
