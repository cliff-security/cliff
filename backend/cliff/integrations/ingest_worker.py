"""Background worker for async chunked finding ingestion (ADR-0023).

A single asyncio coroutine that polls for pending ingest jobs and processes
them chunk-by-chunk through the LLM normalizer. Designed to run alongside
the FastAPI lifespan via ``asyncio.create_task``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from cliff.db.repo_finding import create_finding
from cliff.db.repo_ingest_job import (
    get_ingest_job_raw_data,
    get_job_status,
    get_next_pending_job_id,
    increment_completed_chunk,
    increment_failed_chunk,
    set_job_status,
)
from cliff.integrations.normalizer import normalize_findings

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Consecutive connection failures before backing off
_MAX_CONSECUTIVE_FAILURES = 3
_BACKOFF_SECONDS = 30
_POLL_INTERVAL = 1

# Small imports get per-finding chunks for better progress granularity
_SMALL_IMPORT_THRESHOLD = 5


def estimate_tokens(raw_data: list[dict[str, Any]], chunk_size: int) -> int:
    """Rough token estimate for an ingest job.

    Formula from ADR-0023:
      estimated_tokens = (raw_chars / 3.5) + (num_chunks * 800)
    """
    import json

    raw_chars = len(json.dumps(raw_data, separators=(",", ":")))
    num_chunks = (len(raw_data) + chunk_size - 1) // chunk_size
    return int(raw_chars / 3.5) + (num_chunks * 800)


async def _process_job(db: aiosqlite.Connection, job_id: str) -> None:
    """Process a single ingest job chunk-by-chunk."""
    data = await get_ingest_job_raw_data(db, job_id)
    if data is None:
        logger.warning("Job %s has no raw data — marking failed", job_id)
        await set_job_status(db, job_id, "failed")
        return

    source, raw_data, chunk_size, model = data
    await set_job_status(db, job_id, "processing")

    # For small imports, use per-finding chunks for better progress visibility
    if len(raw_data) <= _SMALL_IMPORT_THRESHOLD:
        chunk_size = 1

    consecutive_failures = 0
    total_chunks = (len(raw_data) + chunk_size - 1) // chunk_size

    for chunk_idx in range(total_chunks):
        # Check for cancellation before each chunk
        status = await get_job_status(db, job_id)
        if status == "cancelled":
            logger.info("Job %s cancelled — stopping", job_id)
            return

        start = chunk_idx * chunk_size
        end = start + chunk_size
        chunk = raw_data[start:end]

        try:
            valid, errors = await normalize_findings(source, chunk, model=model)
            consecutive_failures = 0  # reset on success
        except Exception as exc:
            consecutive_failures += 1
            error_msg = f"Chunk {chunk_idx + 1}: {type(exc).__name__}: {exc}"
            logger.warning(
                "Chunk %d/%d failed: %r", chunk_idx + 1, total_chunks, exc,
                exc_info=True,
            )
            await increment_failed_chunk(db, job_id, error_msg)

            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "Job %s: %d consecutive failures — pausing",
                    job_id,
                    consecutive_failures,
                )
                await set_job_status(db, job_id, "pending")
                return
            continue

        # Chunk-level fallback: if the whole chunk failed, try items one-by-one
        if not valid and len(chunk) > 1:
            logger.info(
                "Job %s chunk %d: batch failed, retrying %d items individually",
                job_id, chunk_idx + 1, len(chunk),
            )
            valid = []
            errors = []
            for item in chunk:
                try:
                    sub_valid, sub_errors = await normalize_findings(
                        source, [item], model=model
                    )
                    valid.extend(sub_valid)
                    errors.extend(sub_errors)
                except Exception as exc:
                    errors.append(f"Individual item fallback: {exc}")

        # Persist valid findings
        findings_count = 0
        for fc in valid:
            try:
                await create_finding(db, fc)
                findings_count += 1
            except Exception as exc:
                logger.warning("Failed to persist finding in chunk %d: %s", chunk_idx + 1, exc)
                errors.append(f"DB error: {exc}")

        await increment_completed_chunk(db, job_id, findings_count)

        if errors:
            for err in errors:
                await increment_failed_chunk(
                    db, job_id, f"Chunk {chunk_idx + 1}: {err}"
                )

        logger.info(
            "Job %s chunk %d/%d: %d findings created",
            job_id,
            chunk_idx + 1,
            total_chunks,
            findings_count,
        )

    # Determine final status
    status = await get_job_status(db, job_id)
    if status == "cancelled":
        return

    # Re-read to check if all chunks failed
    from cliff.db.repo_ingest_job import get_ingest_job

    progress = await get_ingest_job(db, job_id)
    if progress and progress.completed_chunks == 0:
        await set_job_status(db, job_id, "failed")
    else:
        await set_job_status(db, job_id, "completed")


async def ingest_worker_loop(db: aiosqlite.Connection) -> None:
    """Main worker loop — polls for pending jobs and processes them.

    This coroutine runs indefinitely until cancelled.
    """
    logger.info("Ingest worker started")

    while True:
        try:
            job_id = await get_next_pending_job_id(db)
            if job_id:
                logger.info("Processing ingest job %s", job_id)
                await _process_job(db, job_id)
            else:
                await asyncio.sleep(_POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Ingest worker cancelled — shutting down")
            raise
        except Exception:
            logger.exception("Unexpected error in ingest worker")
            await asyncio.sleep(_BACKOFF_SECONDS)
