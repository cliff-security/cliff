"""SidebarState endpoints (nested under workspaces)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cliff.db.connection import get_db
from cliff.db.repo_sidebar import get_sidebar, upsert_sidebar
from cliff.models import SidebarState, SidebarStateUpdate

router = APIRouter(tags=["sidebar"])


@router.put("/workspaces/{workspace_id}/sidebar", response_model=SidebarState)
async def upsert_sidebar_endpoint(
    workspace_id: str, body: SidebarStateUpdate, db=Depends(get_db)
):
    return await upsert_sidebar(db, workspace_id, body)


@router.get("/workspaces/{workspace_id}/sidebar", response_model=SidebarState)
async def get_sidebar_endpoint(workspace_id: str, db=Depends(get_db)):
    sidebar = await get_sidebar(db, workspace_id)
    if not sidebar:
        raise HTTPException(status_code=404, detail="Sidebar state not found")
    return sidebar
