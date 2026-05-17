"""Completion routes (IMPL-0002 Milestone D5).

Fire-and-forget from the frontend; drives the v1.1 share-action rate metric.
Appends to ``completion.share_actions_used`` with insertion-order dedup so repeat
clicks don't skew the metric.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cliff.db.connection import get_db
from cliff.db.dao.completion import (
    get_completion as dao_get_completion,
)
from cliff.db.dao.completion import (
    record_share_action as dao_record_share_action,
)
from cliff.models import Completion, ShareAction

router = APIRouter(prefix="/completion", tags=["completion"])


class ShareActionRequest(BaseModel):
    action: ShareAction


class ShareActionResponse(BaseModel):
    completion_id: str
    share_actions_used: list[ShareAction]


@router.get("/{completion_id}", response_model=Completion)
async def get_completion(
    completion_id: str,
    db=Depends(get_db),
) -> Completion:
    """Read-only fetch — used by the E2E suite to verify share-action recording."""
    completion = await dao_get_completion(db, completion_id)
    if completion is None:
        raise HTTPException(status_code=404, detail="Completion not found")
    return completion


@router.post("/{completion_id}/share-action", response_model=ShareActionResponse)
async def record_share_action(
    completion_id: str,
    request: ShareActionRequest,
    db=Depends(get_db),
) -> ShareActionResponse:
    """Append the share action to the completion's audit row (idempotent)."""
    completion = await dao_record_share_action(db, completion_id, request.action)
    if completion is None:
        raise HTTPException(status_code=404, detail="Completion not found")
    return ShareActionResponse(
        completion_id=completion.id,
        share_actions_used=completion.share_actions_used,
    )
