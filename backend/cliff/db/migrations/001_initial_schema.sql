-- 001_initial_schema.sql
-- Full schema for Cliff domain model.

-- Finding — a vulnerability from a scanner.
CREATE TABLE IF NOT EXISTS finding (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    raw_severity    TEXT,
    normalized_priority TEXT,
    asset_id        TEXT,
    asset_label     TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    likely_owner    TEXT,
    why_this_matters TEXT,
    raw_payload     TEXT,  -- JSON
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finding_status ON finding(status);
CREATE INDEX IF NOT EXISTS idx_finding_source ON finding(source_type, source_id);

-- Workspace — a remediation session for one Finding.
CREATE TABLE IF NOT EXISTS workspace (
    id                  TEXT PRIMARY KEY,
    finding_id          TEXT NOT NULL REFERENCES finding(id),
    state               TEXT NOT NULL DEFAULT 'open',
    current_focus       TEXT,
    active_plan_version INTEGER,
    linked_ticket_id    TEXT,
    validation_state    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_finding ON workspace(finding_id);
CREATE INDEX IF NOT EXISTS idx_workspace_state ON workspace(state);

-- Message — a chat message within a workspace.
CREATE TABLE IF NOT EXISTS message (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    role                TEXT NOT NULL,
    content_markdown    TEXT,
    linked_agent_run_id TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_workspace ON message(workspace_id);

-- AgentRun — a single sub-agent execution.
CREATE TABLE IF NOT EXISTS agent_run (
    id                TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    agent_type        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued',
    input_json        TEXT,  -- JSON
    summary_markdown  TEXT,
    confidence        REAL,
    evidence_json     TEXT,  -- JSON
    structured_output TEXT,  -- JSON
    next_action_hint  TEXT,
    started_at        TEXT,
    completed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_run_workspace ON agent_run(workspace_id);

-- SidebarState — persistent structured context per workspace (1:1).
CREATE TABLE IF NOT EXISTS sidebar_state (
    workspace_id       TEXT PRIMARY KEY REFERENCES workspace(id) ON DELETE CASCADE,
    summary            TEXT,  -- JSON
    evidence           TEXT,  -- JSON
    owner              TEXT,  -- JSON
    plan               TEXT,  -- JSON
    definition_of_done TEXT,  -- JSON
    linked_ticket      TEXT,  -- JSON
    validation         TEXT,  -- JSON
    similar_cases      TEXT,  -- JSON
    updated_at         TEXT NOT NULL
);

-- TicketLink — reference to an external ticket.
CREATE TABLE IF NOT EXISTS ticket_link (
    id               TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,
    external_key     TEXT NOT NULL,
    title            TEXT,
    status           TEXT,
    assignee         TEXT,
    payload_snapshot TEXT,  -- JSON
    last_synced_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticket_link_workspace ON ticket_link(workspace_id);

-- ValidationResult — fix validation outcome.
CREATE TABLE IF NOT EXISTS validation_result (
    id               TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,
    state            TEXT NOT NULL DEFAULT 'not_started',
    details_markdown TEXT,
    evidence         TEXT,  -- JSON
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_validation_result_workspace ON validation_result(workspace_id);

-- AppSetting — key-value app configuration.
CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT,  -- JSON
    updated_at TEXT NOT NULL
);

-- IntegrationConfig — adapter connection configuration.
CREATE TABLE IF NOT EXISTS integration_config (
    id               TEXT PRIMARY KEY,
    adapter_type     TEXT NOT NULL,
    provider_name    TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    config           TEXT,  -- JSON
    last_test_result TEXT,  -- JSON
    updated_at       TEXT NOT NULL
);
