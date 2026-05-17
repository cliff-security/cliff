"""Finding CRUD endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cliff.db.connection import get_db
from cliff.db.repo_finding import (
    create_finding,
    delete_finding,
    get_finding,
    list_findings,
    update_finding,
)
from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job, set_job_status
from cliff.integrations.ingest_worker import estimate_tokens
from cliff.models import (
    Finding,
    FindingCreate,
    FindingUpdate,
    IngestJobProgress,
    IngestJobResponse,
    IngestRequest,
)
from cliff.models.finding import ExceptionReason


class RejectFindingRequest(BaseModel):
    """Body of ``POST /findings/{id}/reject`` (PRD-0006 Phase 2 / IMPL-0007 §B3)."""

    reason: ExceptionReason
    note: str | None = Field(default=None, max_length=280)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["findings"])


@router.post("/findings/ingest", response_model=IngestJobResponse)
async def ingest_findings_endpoint(body: IngestRequest, db=Depends(get_db)):
    """Create an async ingest job for raw scanner findings.

    Returns a job reference immediately. The background worker processes
    chunks asynchronously. Poll ``GET /findings/ingest/{job_id}`` for progress.
    See ADR-0023.
    """
    if not body.raw_data:
        raise HTTPException(status_code=400, detail="raw_data must not be empty")

    chunk_size = max(1, min(body.chunk_size, 50))
    tokens = estimate_tokens(body.raw_data, chunk_size)

    if body.dry_run:
        total_items = len(body.raw_data)
        total_chunks = (total_items + chunk_size - 1) // chunk_size
        return IngestJobResponse(
            job_id="dry-run",
            status="dry_run",
            total_items=total_items,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            estimated_tokens=tokens,
            poll_url="",
        )

    job = await create_ingest_job(
        db,
        source=body.source,
        raw_data=body.raw_data,
        chunk_size=chunk_size,
        model=body.model,
        estimated_tokens=tokens,
    )
    return job


@router.get("/findings/ingest/{job_id}", response_model=IngestJobProgress)
async def get_ingest_progress_endpoint(job_id: str, db=Depends(get_db)):
    """Get progress for an ingest job."""
    progress = await get_ingest_job(db, job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Ingest job not found")
    return progress


@router.post("/findings/ingest/{job_id}/cancel")
async def cancel_ingest_endpoint(job_id: str, db=Depends(get_db)):
    """Cancel a pending or processing ingest job."""
    progress = await get_ingest_job(db, job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Ingest job not found")
    if progress.status not in ("pending", "processing"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job in '{progress.status}' state",
        )
    await set_job_status(db, job_id, "cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@router.post("/findings", response_model=Finding, status_code=201)
async def create_finding_endpoint(body: FindingCreate, db=Depends(get_db)):
    return await create_finding(db, body)


@router.get("/findings", response_model=list[Finding])
async def list_findings_endpoint(
    status: str | None = None,
    has_workspace: bool | None = None,
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db=Depends(get_db),
):
    """List findings.

    When ``scope=current`` the list is scoped to the latest assessment via
    ``assessment_id``. All finding types are included — including posture
    rows — so the Issues page surfaces every actionable item from the
    most recent scan. The dashboard's posture card filters by
    ``type=posture`` if it wants only those.

    Baseline-passing posture rows (``type='posture'`` + ``status='passed'`` +
    no ``pr_url``) are suppressed under ``scope=current``: they were never
    actionable issues, so they should not appear in the Issues page.
    Posture rows that *became* passing via a workspace PR (``pr_url`` is
    set) are still surfaced so the Done section reflects the user's work.
    """
    assessment_id: str | None = None
    if scope == "current":
        from cliff.db.dao.assessment import get_latest_assessment

        latest = await get_latest_assessment(db)
        if latest is None:
            return []
        assessment_id = latest.id

    rows = await list_findings(
        db,
        status=status,
        has_workspace=has_workspace,
        assessment_id=assessment_id,
        limit=limit,
        offset=offset,
    )

    if scope == "current":
        rows = [
            r
            for r in rows
            if not (r.type == "posture" and r.status == "passed" and not r.pr_url)
        ]

    return rows


@router.post("/findings/{finding_id}/reject", response_model=Finding)
async def reject_finding_endpoint(
    finding_id: str,
    body: RejectFindingRequest,
    db=Depends(get_db),
):
    """Mark a finding as an exception with a documented reason (PRD-0006 Phase 2).

    Re-rejecting overrides the prior reason+note — the most recent submission
    wins. The derived ``stage`` field on the response reflects the verdict
    chip the Issues page will render in the Done section.
    """
    updated = await update_finding(
        db,
        finding_id,
        FindingUpdate(
            status="exception",
            exception_reason=body.reason,
            exception_note=body.note,
        ),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return updated


@router.get("/findings/{finding_id}", response_model=Finding)
async def get_finding_endpoint(finding_id: str, db=Depends(get_db)):
    finding = await get_finding(db, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.patch("/findings/{finding_id}", response_model=Finding)
async def update_finding_endpoint(finding_id: str, body: FindingUpdate, db=Depends(get_db)):
    finding = await update_finding(db, finding_id, body)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.delete("/findings/{finding_id}", status_code=204)
async def delete_finding_endpoint(finding_id: str, db=Depends(get_db)):
    deleted = await delete_finding(db, finding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Finding not found")
