# ADR-0023: Async Chunked Finding Ingestion with Cost Controls

**Date:** 2026-04-06
**Status:** Proposed

## Context

The current `POST /api/findings/ingest` endpoint (implemented per ADR-0022 Part 1) is synchronous: it sends all raw findings to the LLM in a single call via the singleton OpenCode process and blocks until the response is complete. This was acceptable for the initial implementation but does not scale.

Testing in Docker revealed concrete problems:

1. **Blocking duration.** OpenCode's `POST /session/{id}/message` blocks until the LLM finishes generating the complete response. For 3 findings with gpt-4.1-nano, this takes 60-120+ seconds. The HTTP request sits open the entire time.

2. **Context window limits.** The normalizer prompt includes the full schema, two few-shot examples, and then the entire raw data payload. For 100+ findings, the combined token count exceeds most models' context windows — particularly the cheaper models (GPT-4.1-mini, Haiku) that are ideal for structured extraction.

3. **All-or-nothing failure.** If the LLM flakes mid-batch, stalls, or returns malformed JSON, the entire ingest is lost. There is no partial progress and no retry mechanism.

4. **No cost visibility.** Users have no indication of how many tokens an ingest will consume before it runs. Bulk imports from enterprise scanners (thousands of findings) could incur surprising costs.

5. **Singleton contention.** The singleton OpenCode process handles all app-level tasks. A long-running normalization blocks other uses of that process (health checks still work, but any other agent task would queue behind it).

The existing `normalize_findings()` function in `backend/cliff/integrations/normalizer.py` already has a `MAX_BATCH_SIZE = 50` limit, but this is a hard reject — it does not chunk. The prompt, JSON extraction, and Pydantic validation logic are solid and should be preserved.

## Decision

Replace the synchronous ingest with a job-based async system that chunks large batches and processes them incrementally. Three parts: async job lifecycle, cost controls, and model override.

### Part 1: Job-based async processing

**New endpoint behavior:**

- `POST /api/findings/ingest` accepts the same `IngestRequest` body (`{ source, raw_data[] }`). It validates the payload shape, creates an `ingest_job` record in SQLite, and returns immediately with:
  ```json
  {
    "job_id": "abc-123",
    "status": "pending",
    "total_items": 200,
    "chunk_size": 10,
    "total_chunks": 20,
    "estimated_tokens": 42000,
    "poll_url": "/api/findings/ingest/abc-123"
  }
  ```
  It does NOT call the LLM. HTTP response time: < 100ms.

- `GET /api/findings/ingest/{job_id}` returns current progress:
  ```json
  {
    "job_id": "abc-123",
    "status": "processing",
    "total_items": 200,
    "total_chunks": 20,
    "completed_chunks": 12,
    "failed_chunks": 1,
    "findings_created": 108,
    "errors": ["Chunk 7: LLM returned empty response"],
    "created_at": "...",
    "updated_at": "..."
  }
  ```

- `POST /api/findings/ingest/{job_id}/cancel` sets status to `cancelled`. The background worker checks status before processing each chunk and stops if cancelled.

**Background worker:**

An asyncio background task, started during FastAPI lifespan (alongside the existing OpenCode process startup). Not a separate process, not Celery, not a thread pool — a single `asyncio.create_task` coroutine that polls for pending jobs.

The worker loop:
1. Query SQLite for the oldest job with `status = 'pending'` or `status = 'processing'` (resume after restart).
2. Split `raw_data` into chunks of `chunk_size` items (default 10, stored on the job record).
3. For each chunk, call `normalize_findings()` (the existing function, with the batch limited to chunk size).
4. On success: persist findings to DB, increment `completed_chunks` and `findings_created`, update `updated_at`.
5. On failure: increment `failed_chunks`, append error to `errors` JSON array, continue to next chunk.
6. After all chunks: set status to `completed` (or `failed` if all chunks failed).
7. Sleep briefly (1 second) before polling for the next job.

**Why a polling worker instead of spawning a task per job:**

A single sequential worker is simpler and avoids concurrent access to the singleton OpenCode process. The OpenCode process handles one session at a time effectively — parallelizing chunks would not help because they would serialize at the LLM call anyway. If throughput becomes a bottleneck later, we can add concurrency with a semaphore.

**Retry policy:**

Failed chunks are not automatically retried during the initial run. The job record retains `raw_data`, so a future `POST /api/findings/ingest/{job_id}/retry` endpoint can re-queue only the failed chunks. This is post-MVP — for now, users can see which chunks failed and re-submit if needed.

### Part 2: Cost controls

**Token estimation:**

Before creating the job, estimate the token cost:
- Count raw characters in the serialized `raw_data` JSON.
- Apply a conservative ratio: 1 token per 3.5 characters (covers JSON overhead and the prompt template).
- Add the fixed prompt overhead (~800 tokens for the normalizer prompt + few-shot examples) per chunk.
- Formula: `estimated_tokens = (raw_chars / 3.5) + (num_chunks * 800)`

This is a rough estimate, not exact. It is included in the job creation response so the frontend can display it. No confirmation gate on the backend — the frontend decides whether to show a warning dialog based on the estimate.

**Dry-run mode:**

`POST /api/findings/ingest` accepts an optional `dry_run: true` field. When set, the endpoint returns the estimation without creating a job record. This lets the frontend show a preview: "This will process 200 findings in 20 chunks, estimated 42,000 tokens."

**Model override:**

The ingest request accepts an optional `model` field (e.g., `"openai/gpt-4.1-mini"`). Resolution order:
1. Per-request `model` field (if provided in the `IngestRequest`).
2. App setting `normalizer_model` (persisted in the `app_setting` table, configurable from Settings page).
3. The singleton OpenCode process's configured default model.

For the initial implementation, the model override is **recorded on the job record but not enforced at the OpenCode level**. The reason: OpenCode's session API does not currently support per-session model selection. The singleton process uses whatever model is configured globally. To use a different model for normalization, the user changes the app's default model in Settings (which already works via `PATCH /config`).

A future enhancement could temporarily switch the model before each chunk and restore it after, but this introduces race conditions with other concurrent uses of the singleton process. The cleaner long-term path is for OpenCode to support per-session model overrides — we should track this as an upstream feature request.

For now, the `model` field on the job serves as:
- Documentation of intent ("I wanted this processed with gpt-4.1-mini").
- Input for the cost estimator (different models have different per-token costs).
- A hook point for when per-session model selection becomes available.

### Part 3: DB schema

New table `ingest_job`:

```sql
CREATE TABLE IF NOT EXISTS ingest_job (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'pending',
    source        TEXT NOT NULL,
    total_items   INTEGER NOT NULL,
    chunk_size    INTEGER NOT NULL DEFAULT 10,
    total_chunks  INTEGER NOT NULL,
    completed_chunks INTEGER NOT NULL DEFAULT 0,
    failed_chunks INTEGER NOT NULL DEFAULT 0,
    findings_created INTEGER NOT NULL DEFAULT 0,
    model         TEXT,
    estimated_tokens INTEGER,
    errors        TEXT DEFAULT '[]',
    raw_data      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

Status values: `pending`, `processing`, `completed`, `failed`, `cancelled`.

**Raw data cleanup policy:** `raw_data` is retained for 7 days after job completion, then NULLed out by a cleanup sweep (run as part of the background worker's idle loop). This allows retries of recent failures while preventing unbounded storage growth. The 7-day period is configurable via `CLIFF_INGEST_RETENTION_DAYS` (default 7).

### Part 4: Updated models

```python
class IngestRequest(BaseModel):
    source: str
    raw_data: list[dict[str, Any]]
    model: str | None = None       # optional model override
    chunk_size: int = 10           # items per LLM call (1-50)
    dry_run: bool = False          # estimate only, do not create job

class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    total_items: int
    chunk_size: int
    total_chunks: int
    estimated_tokens: int | None = None
    poll_url: str

class IngestJobProgress(BaseModel):
    job_id: str
    status: str
    total_items: int
    total_chunks: int
    completed_chunks: int
    failed_chunks: int
    findings_created: int
    errors: list[str]
    created_at: str
    updated_at: str
```

The existing `IngestResult` model (returning `created: list[Finding]`) is deprecated. The new flow returns a job reference, not the findings themselves. Findings are accessible via the existing `GET /api/findings` endpoint, filtered by creation time or source.

### Part 5: What stays the same

- The normalizer prompt in `normalizer.py` — unchanged.
- The `_extract_json_array()` parser — unchanged.
- The `FindingCreate` Pydantic validation — unchanged.
- The `create_finding()` DB function — unchanged.
- The singleton OpenCode process architecture — unchanged.
- The `GET /api/findings` and other CRUD endpoints — unchanged.

The `normalize_findings()` function signature stays the same but its `MAX_BATCH_SIZE` is relaxed (or removed), since the chunking layer above it guarantees each call receives at most `chunk_size` items.

## Design review notes

**Is the job queue the simplest approach that works?**

Considered alternatives:
- **Streaming response (SSE from the ingest endpoint):** Simpler in theory — no job table, no polling. But it requires the HTTP connection to stay open for the entire multi-minute processing time. Proxies, load balancers, and browser fetch APIs handle long-lived SSE poorly for POST requests. It also prevents the user from navigating away and coming back to check progress.
- **Fire-and-forget with webhook/callback:** Even simpler — no progress tracking at all. But users need to know when their import is done and whether it succeeded. Without progress, the UX is "click and pray."
- **In-memory queue (no DB persistence):** Simpler — no new table. But jobs are lost on restart, and there is no way to resume after a crash. Given that ingest can take 10+ minutes for large batches, persistence is worth the complexity.

The job table approach is the simplest design that supports: progress tracking, crash recovery, cancellation, and future retry. It adds one table and one background coroutine.

**Chunk size: is 10 the right default?**

The normalizer prompt is ~800 tokens. Each raw finding averages 200-500 tokens depending on vendor format. At chunk size 10, a chunk is roughly 3,000-6,000 tokens input + 2,000-4,000 tokens output. This fits comfortably in any model's context window, including small local models via Ollama.

Making it configurable per-request (with a default of 10 and a max of 50) is the right call. Power users running local models with large context windows can increase it; users with verbose findings can decrease it.

**What happens when the OpenCode process is down?**

The background worker catches connection errors from `opencode_client` and treats them as chunk failures. After 3 consecutive connection failures, the worker pauses the job (sets status back to `pending`) and backs off for 30 seconds before retrying. When the OpenCode process comes back (detected via `health_check()`), the worker resumes pending jobs automatically.

**Singleton contention:**

The background worker processes one chunk at a time, sequentially. Each chunk creates a new OpenCode session, sends the prompt, waits for the response, and then moves on. Between chunks, other app-level tasks can use the singleton process. This is cooperative concurrency — the worker does not hold a lock on the process, but each chunk does occupy it for 20-60 seconds.

If this becomes a problem, the long-term fix is a dedicated OpenCode process for normalization (separate from the singleton). But for MVP, the singleton is sufficient.

## Consequences

**Easier:**
- Bulk ingest of 100+ findings works reliably — no timeouts, no context window overflow
- Partial progress is visible — users know exactly how far along their import is
- Failed chunks do not block successful ones — partial imports are useful
- Cost is estimated before processing starts — no surprise bills
- Crash recovery — jobs resume after restart
- Cancellation — users can stop a long-running import
- Model override is future-proofed even though per-session selection is not yet available

**Harder:**
- More moving parts than the synchronous version (job table, background worker, polling endpoint)
- Frontend needs a progress UI (polling `GET /api/findings/ingest/{job_id}` on an interval)
- Testing requires mocking the background worker lifecycle
- Raw data stored in SQLite temporarily increases DB size (mitigated by 7-day cleanup)
- The synchronous `IngestResult` response model is deprecated — any frontend code using it needs to adapt to the async flow
