-- 0017_ai_integration.sql
-- ADR-0036 / IMPL-0011 — Tiered AI provider onboarding.
--
-- Tracks the active AI provider integration (one row per provider per
-- ADR-0036; community edition is effectively single-row).
--
-- Secrets stay in the credential vault (table ``credential``) — this table
-- holds non-secret metadata (provider name, source of the key, when it was
-- connected, when it was last validated). The API key itself lives in
-- ``credential`` under ``key_name = 'api_key'`` namespaced by
-- ``integration_id``.
--
-- Timestamps are TEXT (ISO 8601 strings) to match the rest of the schema.
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

CREATE TABLE IF NOT EXISTS ai_integration (
    id              TEXT PRIMARY KEY,
    integration_id  TEXT NOT NULL UNIQUE
                    REFERENCES integration_config(id) ON DELETE CASCADE,

    provider        TEXT NOT NULL
                    CHECK (provider IN ('openrouter','anthropic','openai','custom')),

    -- How the key arrived. Three discrete sources, audited at adoption time.
    source          TEXT NOT NULL
                    CHECK (source IN ('autodetect','openrouter-oauth','byok')),

    -- Free-form provider-specific metadata as JSON: OpenRouter user_email,
    -- autodetect source path, custom base_url, etc. Never stores key
    -- material.
    metadata_json   TEXT,

    connected_at      TEXT NOT NULL,
    last_validated_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- One active row per provider — single-user community edition.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_integration_provider
    ON ai_integration(provider);
