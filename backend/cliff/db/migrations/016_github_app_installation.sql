-- 016_github_app_installation.sql
-- ADR-0035 / IMPL-0010 — GitHub App + Device Flow onboarding.
--
-- Tracks per-installation state for the device flow. All secrets stay in
-- the credential vault (table ``credential``) — this table holds non-secret
-- metadata (installation_id, csrf state, polling status, expiry timestamps).
-- The in-flight device_code itself is stored in the credential vault under
-- key_name ``github_device_code`` and cleared on terminal state.
--
-- Timestamps are TEXT (ISO 8601 strings) to match the rest of the schema
-- (``credential.created_at``, ``integration_config.updated_at``, etc.).
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

CREATE TABLE IF NOT EXISTS github_app_installation (
    id              TEXT PRIMARY KEY,
    integration_id  TEXT NOT NULL UNIQUE
                    REFERENCES integration_config(id) ON DELETE CASCADE,

    -- App identity at time of install (snapshot for support).
    app_slug        TEXT NOT NULL,
    client_id       TEXT NOT NULL,

    -- GitHub-issued installation ID (set after /setup callback).
    installation_id INTEGER,
    installation_completed_at TEXT,

    -- CSRF token bound to the install URL we generated. Validated on /setup.
    csrf_state      TEXT NOT NULL UNIQUE,

    -- In-flight device code metadata (cleared once status is terminal).
    user_code            TEXT,
    verification_uri     TEXT,
    device_code_expires_at TEXT,
    polling_interval_seconds INTEGER,

    -- Current state of the polling state machine.
    polling_status   TEXT NOT NULL DEFAULT 'installation_pending'
                     CHECK (polling_status IN (
                         'installation_pending',
                         'device_pending',
                         'connected',
                         'expired',
                         'denied',
                         'rate_limited',
                         'error'
                     )),
    polling_error    TEXT,
    last_polled_at   TEXT,

    -- Token lifetime (nullable — present only when token expiry is enabled
    -- on the App). Token itself lives in the credential vault.
    token_expires_at TEXT,

    -- Identity of the user who authorized (populated post-connect via /user).
    github_login     TEXT,

    -- Last successful validation against GitHub (e.g. via GET /user).
    last_validated_at TEXT,

    connected_at     TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_github_app_installation_csrf
    ON github_app_installation(csrf_state);
