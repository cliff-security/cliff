"""Session management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cliff.engine.client import opencode_client
from cliff.engine.models import SessionDetail, SessionSummary

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionSummary)
async def create_session() -> SessionSummary:
    """Create a new OpenCode session."""
    try:
        return await opencode_client.create_session()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenCode error: {e}") from e


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions() -> list[SessionSummary]:
    """List all active sessions."""
    try:
        return await opencode_client.list_sessions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenCode error: {e}") from e


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str) -> SessionDetail:
    """Get session details including message history."""
    try:
        return await opencode_client.get_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenCode error: {e}") from e
