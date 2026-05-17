-- Async chunked finding ingestion job table (ADR-0023)
CREATE TABLE IF NOT EXISTS ingest_job (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'pending',
    source           TEXT NOT NULL,
    total_items      INTEGER NOT NULL,
    chunk_size       INTEGER NOT NULL DEFAULT 10,
    total_chunks     INTEGER NOT NULL,
    completed_chunks INTEGER NOT NULL DEFAULT 0,
    failed_chunks    INTEGER NOT NULL DEFAULT 0,
    findings_created INTEGER NOT NULL DEFAULT 0,
    model            TEXT,
    estimated_tokens INTEGER,
    errors           TEXT DEFAULT '[]',
    raw_data         TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
