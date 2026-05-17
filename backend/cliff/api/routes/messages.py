"""Message endpoints (nested under workspaces)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cliff.db.connection import get_db
from cliff.db.repo_message import create_message, delete_message, get_message, list_messages
from cliff.models import Message, MessageCreate

router = APIRouter(tags=["messages"])


@router.post("/workspaces/{workspace_id}/messages", response_model=Message, status_code=201)
async def create_message_endpoint(
    workspace_id: str, body: MessageCreate, db=Depends(get_db)
):
    return await create_message(db, workspace_id, body)


@router.get("/workspaces/{workspace_id}/messages", response_model=list[Message])
async def list_messages_endpoint(
    workspace_id: str,
    limit: int = 200,
    offset: int = 0,
    db=Depends(get_db),
):
    return await list_messages(db, workspace_id, limit=limit, offset=offset)


@router.get(
    "/workspaces/{workspace_id}/messages/{message_id}",
    response_model=Message,
)
async def get_message_endpoint(workspace_id: str, message_id: str, db=Depends(get_db)):
    msg = await get_message(db, message_id)
    if not msg or msg.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.delete("/workspaces/{workspace_id}/messages/{message_id}", status_code=204)
async def delete_message_endpoint(workspace_id: str, message_id: str, db=Depends(get_db)):
    msg = await get_message(db, message_id)
    if not msg or msg.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Message not found")
    await delete_message(db, message_id)
