-- 0020_ai_integration_google_ollama.sql
-- ADR-0037 — Unified AI provider config: add Google + Ollama provider literals.
--
-- SQLite has no ALTER TABLE for CHECK constraints; we rebuild the table
-- preserving rows, the unique index, and the FK cascade.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS ai_integration_new (
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

PRAGMA foreign_keys = ON;
