"""API routes for the integration audit log (ADR-0017)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Request

if TYPE_CHECKING:
    import aiosqlite

from cliff.db import repo_audit
from cliff.db.connection import get_db

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def query_audit_log(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    workspace_id: str | None = Query(None),
    integration_id: str | None = Query(None),
    event_type: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 timestamp"),
    until: str | None = Query(None, description="ISO 8601 timestamp"),
    correlation_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Query audit events with optional filters."""
    events = await repo_audit.query_audit_log(
        db,
        workspace_id=workspace_id,
        integration_id=integration_id,
        event_type=event_type,
        since=since,
        until=until,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )
    total = await repo_audit.count_audit_events(
        db,
        workspace_id=workspace_id,
        integration_id=integration_id,
        event_type=event_type,
        since=since,
        until=until,
    )
    return {"events": events, "total": total, "limit": limit, "offset": offset}
