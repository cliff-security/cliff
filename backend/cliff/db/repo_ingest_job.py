"""Repository functions for the ingest_job entity (ADR-0023)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cliff.models import IngestJobProgress, IngestJobResponse

if TYPE_CHECKING:
    import aiosqlite

# ---------------------------------------------------------------------------
# Row → model helpers
# ---------------------------------------------------------------------------


def _row_to_progress(row: aiosqlite.Row) -> IngestJobProgress:
    return IngestJobProgress(
        job_id=row["id"],
        status=row["status"],
        total_items=row["total_items"],
        total_chunks=row["total_chunks"],
        completed_chunks=row["completed_chunks"],
        failed_chunks=row["failed_chunks"],
        findings_created=row["findings_created"],
        errors=json.loads(row["errors"]) if row["errors"] else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_response(row: aiosqlite.Row) -> IngestJobResponse:
    return IngestJobResponse(
        job_id=row["id"],
        status=row["status"],
        total_items=row["total_items"],
        chunk_size=row["chunk_size"],
        total_chunks=row["total_chunks"],
        estimated_tokens=row["estimated_tokens"],
        poll_url=f"/api/findings/ingest/{row['id']}",
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_ingest_job(
    db: aiosqlite.Connection,
    *,
    source: str,
    raw_data: list[dict[str, Any]],
    chunk_size: int = 10,
    model: str | None = None,
    estimated_tokens: int | None = None,
) -> IngestJobResponse:
    job_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    total_items = len(raw_data)
    total_chunks = (total_items + chunk_size - 1) // chunk_size  # ceiling division

    await db.execute(
        """
        INSERT INTO ingest_job
            (id, status, source, total_items, chunk_size, total_chunks,
             model, estimated_tokens, raw_data, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            "pending",
            source,
            total_items,
            chunk_size,
            total_chunks,
            model,
            estimated_tokens,
            json.dumps(raw_data),
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM ingest_job WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    return _row_to_response(row)  # type: ignore[arg-type]


async def get_ingest_job(
    db: aiosqlite.Connection, job_id: str
) -> IngestJobProgress | None:
    cursor = await db.execute("SELECT * FROM ingest_job WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    return _row_to_progress(row) if row else None


async def get_ingest_job_raw_data(
    db: aiosqlite.Connection, job_id: str
) -> tuple[str, list[dict[str, Any]], int, str | None] | None:
    """Return (source, raw_data, chunk_size, model) for the worker to process."""
    cursor = await db.execute(
        "SELECT source, raw_data, chunk_size, model FROM ingest_job WHERE id = ?",
        (job_id,),
    )
    row = await cursor.fetchone()
    if not row or not row["raw_data"]:
        return None
    return row["source"], json.loads(row["raw_data"]), row["chunk_size"], row["model"]


async def get_next_pending_job_id(db: aiosqlite.Connection) -> str | None:
    """Return the oldest pending or processing job ID (for resume after restart)."""
    cursor = await db.execute(
        "SELECT id FROM ingest_job WHERE status IN ('pending', 'processing') "
        "ORDER BY created_at ASC LIMIT 1",
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def set_job_status(
    db: aiosqlite.Connection, job_id: str, status: str
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE ingest_job SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, job_id),
    )
    await db.commit()


async def increment_completed_chunk(
    db: aiosqlite.Connection, job_id: str, findings_count: int
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE ingest_job SET "
        "completed_chunks = completed_chunks + 1, "
        "findings_created = findings_created + ?, "
        "updated_at = ? WHERE id = ?",
        (findings_count, now, job_id),
    )
    await db.commit()


async def increment_failed_chunk(
    db: aiosqlite.Connection, job_id: str, error: str
) -> None:
    now = datetime.now(UTC).isoformat()
    # Append error to the JSON array
    cursor = await db.execute(
        "SELECT errors FROM ingest_job WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    errors = json.loads(row["errors"]) if row and row["errors"] else []
    errors.append(error)

    await db.execute(
        "UPDATE ingest_job SET "
        "failed_chunks = failed_chunks + 1, "
        "errors = ?, "
        "updated_at = ? WHERE id = ?",
        (json.dumps(errors), now, job_id),
    )
    await db.commit()


async def get_job_status(db: aiosqlite.Connection, job_id: str) -> str | None:
    cursor = await db.execute(
        "SELECT status FROM ingest_job WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    return row["status"] if row else None
