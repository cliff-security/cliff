-- 0020_ai_integration_google_ollama.sql
-- ADR-0037 — Unified AI provider config: add Google + Ollama provider literals.
--
-- SQLite has no ALTER TABLE for CHECK constraints; we rebuild the table
-- preserving rows, the unique index, and the FK cascade.
--
-- H2 fix: ``PRAGMA foreign_keys`` is a no-op inside a transaction, and
-- ``executescript`` runs each statement under its own implicit txn — so
-- the previous ``foreign_keys = OFF`` couldn't be relied on, and the
-- ``DROP TABLE ai_integration`` would trip the ``integration_config →
-- ai_integration`` cascade on any installed instance that already held
-- a row, silently losing the user's AI integration on upgrade.
--
-- Correct pattern for SQLite table-rebuilds: wrap everything in one
-- explicit transaction and use ``PRAGMA defer_foreign_keys = ON`` —
-- that DOES work inside a transaction; FKs are checked only at commit.

BEGIN;
PRAGMA defer_foreign_keys = ON;

CREATE TABLE ai_integration_new (
    id              TEXT PRIMARY KEY,
    integration_id  TEXT NOT NULL UNIQUE
                    REFERENCES integration_config(id) ON DELETE CASCADE,

    provider        TEXT NOT NULL
                    CHECK (provider IN (
                        'openrouter','anthropic','openai',
                        'google','ollama','custom'
                    )),

    source          TEXT NOT NULL
                    CHECK (source IN ('autodetect','openrouter-oauth','byok')),

    metadata_json   TEXT,

    connected_at      TEXT NOT NULL,
    last_validated_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

INSERT INTO ai_integration_new
SELECT id, integration_id, provider, source, metadata_json,
       connected_at, last_validated_at, created_at, updated_at
FROM ai_integration;

DROP TABLE ai_integration;
ALTER TABLE ai_integration_new RENAME TO ai_integration;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_integration_provider
    ON ai_integration(provider);

COMMIT;
