-- 025_repo_entity.sql — ADR-0053: first-class git-repository entity.
--
-- Repo identity was a raw URL string duplicated across assessment/workspace/
-- integration_config with no normalization. This table is the canonical home,
-- keyed by canonical_url (cliff.repos.identity.canonicalize_repo_url), and the
-- queryable store for Project-profile freshness.
--
-- One-build-per-repo (ADR-0053 §6) is enforced by a compare-and-swap on
-- profile_status (DAO try_begin_profile), NOT a partial unique index: because
-- canonical_url is globally UNIQUE there is exactly one row per repo, so a
-- partial unique index on canonical_url WHERE building would be strictly
-- redundant with the UNIQUE constraint. The CAS is the honest mutex here.

CREATE TABLE IF NOT EXISTS repo (
    id                 TEXT PRIMARY KEY,
    canonical_url      TEXT NOT NULL UNIQUE,
    default_branch     TEXT,
    last_profiled_sha  TEXT,
    profiled_at        TEXT,
    profile_status     TEXT NOT NULL DEFAULT 'none'
        CHECK (profile_status IN ('none', 'building', 'ready', 'stale', 'error')),
    profile_dir        TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
