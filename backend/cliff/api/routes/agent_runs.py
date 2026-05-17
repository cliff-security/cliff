"""AgentRun endpoints (nested under workspaces)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cliff.db.connection import get_db
from cliff.db.repo_agent_run import (
    create_agent_run,
    get_agent_run,
    list_agent_runs,
    update_agent_run,
)
from cliff.models import AgentRun, AgentRunCreate, AgentRunUpdate

router = APIRouter(tags=["agent-runs"])


@router.post(
    "/workspaces/{workspace_id}/agent-runs",
    response_model=AgentRun,
    status_code=201,
)
async def create_agent_run_endpoint(
    workspace_id: str, body: AgentRunCreate, db=Depends(get_db)
):
    return await create_agent_run(db, workspace_id, body)


@router.get("/workspaces/{workspace_id}/agent-runs", response_model=list[AgentRun])
async def list_agent_runs_endpoint(
    workspace_id: str,
    limit: int = 100,
    offset: int = 0,
    db=Depends(get_db),
):
    return await list_agent_runs(db, workspace_id, limit=limit, offset=offset)


@router.get(
    "/workspaces/{workspace_id}/agent-runs/{run_id}",
    response_model=AgentRun,
)
async def get_agent_run_endpoint(workspace_id: str, run_id: str, db=Depends(get_db)):
    run = await get_agent_run(db, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.patch(
    "/workspaces/{workspace_id}/agent-runs/{run_id}",
    response_model=AgentRun,
)
async def update_agent_run_endpoint(
    workspace_id: str, run_id: str, body: AgentRunUpdate, db=Depends(get_db)
):
    run = await get_agent_run(db, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return await update_agent_run(db, run_id, body)
