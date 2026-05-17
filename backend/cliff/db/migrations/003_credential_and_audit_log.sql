-- 003_credential_and_audit_log.sql
-- Phase I-0: Credential Vault (ADR-0016) and Audit Logging (ADR-0017).

-- Credential — encrypted secret storage per integration.
CREATE TABLE IF NOT EXISTS credential (
    id              TEXT PRIMARY KEY,
    integration_id  TEXT NOT NULL REFERENCES integration_config(id) ON DELETE CASCADE,
    key_name        TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    iv              BLOB NOT NULL,
    created_at      TEXT NOT NULL,
    rotated_at      TEXT,
    UNIQUE(integration_id, key_name)
);
CREATE INDEX IF NOT EXISTS idx_credential_integration ON credential(integration_id);

-- AuditLog — append-only integration audit trail with hash-chain tamper evidence.
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    actor_type      TEXT NOT NULL DEFAULT 'user',
    actor_id        TEXT,
    workspace_id    TEXT,
    integration_id  TEXT,
    provider_name   TEXT,
    tool_name       TEXT,
    verb            TEXT,
    action_tier     INTEGER DEFAULT 0,
    status          TEXT NOT NULL,
    duration_ms     INTEGER,
    parameters_hash TEXT,
    error_message   TEXT,
    correlation_id  TEXT,
    prev_hash       TEXT,
    event_hash      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_workspace ON audit_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_integration ON audit_log(integration_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_correlation ON audit_log(correlation_id);
