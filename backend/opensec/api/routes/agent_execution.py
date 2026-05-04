"""Agent execution endpoints — trigger, stream, cancel, suggest-next."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from opensec.agents.errors import AgentBusyError, AgentProcessError
from opensec.agents.pipeline import VALID_AGENT_TYPES, suggest_next
from opensec.api.routes.workspaces import _resolve_repo_env_vars
from opensec.db.connection import get_db
from opensec.db.repo_agent_run import get_agent_run, update_agent_run
from opensec.db.repo_sidebar import get_sidebar
from opensec.db.repo_workspace import get_workspace
from opensec.models import AgentRunUpdate, SidebarState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-execution"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ExecuteResponse(BaseModel):
    agent_run_id: str
    agent_type: str
    status: str


class ExecuteAgentRequest(BaseModel):
    """Optional body for ``POST /workspaces/{id}/agents/{type}/execute``.

    PRD-0006 Phase 2 / IMPL-0007 §B4 — adds ``user_note`` for the planner's
    Refine flow. Other agent types accept the body but ignore the note.
    """

    user_note: str | None = Field(default=None, max_length=2000)


class SuggestNextResponse(BaseModel):
    agent_type: str | None
    reason: str | None
    priority: str | None
    action_type: str | None = None


# ---------------------------------------------------------------------------
# Agent chips (UI metadata)
# ---------------------------------------------------------------------------


class AgentChipResponse(BaseModel):
    agent_type: str
    label: str
    icon: str


@router.get("/agents/chips", response_model=list[AgentChipResponse])
async def list_agent_chips():
    """Return the ordered list of action chips for the UI."""
    from opensec.agents.registry import AGENT_CHIPS

    return [
        AgentChipResponse(agent_type=c.agent_type, label=c.label, icon=c.icon)
        for c in AGENT_CHIPS
    ]


# ---------------------------------------------------------------------------
# Execute agent
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/agents/{agent_type}/execute",
    response_model=ExecuteResponse,
    status_code=202,
)
async def execute_agent(
    workspace_id: str,
    agent_type: str,
    request: Request,
    db=Depends(get_db),
    body: ExecuteAgentRequest | None = Body(default=None),
):
    """Start an agent run as a background task.

    Returns immediately with the agent_run_id. Connect to the
    agent-execution SSE stream to receive permission_request events
    and a done signal.

    Optional body ``{user_note}`` is forwarded to the planner's prompt for
    PRD-0006 Phase 2's Refine flow; other agent types ignore it.
    """
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not workspace.workspace_dir:
        raise HTTPException(status_code=400, detail="Workspace has no directory")

    if agent_type not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent_type. Must be one of: {sorted(VALID_AGENT_TYPES)}",
        )

    executor = request.app.state.agent_executor

    # Pre-flight check: fail fast if another agent is already running.
    try:
        await executor.check_not_busy(db, workspace_id)
    except AgentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Resolve GitHub env vars (GH_TOKEN, OPENSEC_REPO_URL) for the workspace process.
    env_vars = await _resolve_repo_env_vars(request, db)
    user_note = body.user_note if body else None

    # Launch execution as a background task so we can return immediately.
    async def _run_in_background() -> None:
        try:
            await executor.execute(
                workspace_id,
                agent_type,
                db,
                workspace_dir=workspace.workspace_dir,
                on_permission=lambda evt: executor.push_permission_event(
                    workspace_id, evt
                ),
                env_vars=env_vars,
                user_note=user_note,
            )
        except (AgentBusyError, AgentProcessError):
            logger.exception(
                "Agent execution failed for workspace %s", workspace_id
            )
        except Exception:
            logger.exception(
                "Unexpected error in background agent execution for workspace %s",
                workspace_id,
            )

    asyncio.create_task(_run_in_background())

    # Wait for execute() to register the run ID (set at the top of execute()).
    # Uses a short-polling loop instead of a fixed sleep to avoid races.
    for _ in range(10):
        await asyncio.sleep(0.01)
        run_id = executor.get_active_run_id(workspace_id)
        if run_id:
            break
    else:
        run_id = "pending"

    return ExecuteResponse(
        agent_run_id=run_id or "pending",
        agent_type=agent_type,
        status="running",
    )


# ---------------------------------------------------------------------------
# Suggest next agent
# ---------------------------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/pipeline/suggest-next",
    response_model=SuggestNextResponse,
)
async def suggest_next_endpoint(
    workspace_id: str,
    request: Request,
    db=Depends(get_db),
):
    """Return the recommended next agent based on current context state."""
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    context_builder = request.app.state.context_builder

    try:
        snapshot = await context_builder.get_context_snapshot(workspace_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Workspace directory not found"
        ) from exc

    run_history = snapshot.pop("agent_run_history", [])
    suggestion = suggest_next(snapshot, run_history)

    if suggestion is None:
        return SuggestNextResponse(
            agent_type=None, reason="Pipeline complete", priority=None
        )

    return SuggestNextResponse(
        agent_type=suggestion.agent_type,
        reason=suggestion.reason,
        priority=suggestion.priority,
        action_type=suggestion.action_type,
    )


# ---------------------------------------------------------------------------
# Run full pipeline
# ---------------------------------------------------------------------------


class RunAllResponse(BaseModel):
    status: str
    message: str


@router.post(
    "/workspaces/{workspace_id}/pipeline/run-all",
    response_model=RunAllResponse,
    status_code=202,
)
async def run_all_pipeline(
    workspace_id: str,
    request: Request,
    db=Depends(get_db),
):
    """Run all remaining agents in pipeline order as a background task.

    Each agent runs sequentially. Progress events stream via the
    agent-execution SSE endpoint. Stops on first failure.
    """
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not workspace.workspace_dir:
        raise HTTPException(status_code=400, detail="Workspace has no directory")

    executor = request.app.state.agent_executor
    context_builder = request.app.state.context_builder

    try:
        await executor.check_not_busy(db, workspace_id)
    except AgentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    env_vars = await _resolve_repo_env_vars(request, db)

    async def _run_pipeline() -> None:
        max_iterations = len(VALID_AGENT_TYPES) + 3  # generous upper bound
        consecutive_failures = 0
        max_consecutive_failures = 2

        try:
            for _i in range(max_iterations):
                snapshot = await context_builder.get_context_snapshot(
                    workspace_id
                )
                run_history = snapshot.pop("agent_run_history", [])
                suggestion = suggest_next(snapshot, run_history)

                if (
                    suggestion is None
                    or suggestion.action_type != "run_agent"
                    or suggestion.agent_type is None
                ):
                    break

                agent_type = suggestion.agent_type
                logger.info(
                    "Pipeline auto-run: %s for workspace %s",
                    agent_type,
                    workspace_id,
                )

                try:
                    await executor.execute(
                        workspace_id,
                        agent_type,
                        db,
                        workspace_dir=workspace.workspace_dir,
                        on_permission=lambda evt: (
                            executor.push_permission_event(workspace_id, evt)
                        ),
                        env_vars=env_vars,
                    )
                    consecutive_failures = 0
                except (AgentBusyError, AgentProcessError):
                    consecutive_failures += 1
                    logger.exception(
                        "Pipeline agent %s failed for workspace %s "
                        "(consecutive failures: %d/%d)",
                        agent_type,
                        workspace_id,
                        consecutive_failures,
                        max_consecutive_failures,
                    )
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            "Pipeline stopped after %d consecutive failures "
                            "for workspace %s",
                            consecutive_failures,
                            workspace_id,
                        )
                        break
        except Exception:
            logger.exception(
                "Unexpected error in pipeline run-all for workspace %s",
                workspace_id,
            )

    asyncio.create_task(_run_pipeline())

    return RunAllResponse(
        status="running",
        message="Pipeline started — agents will run sequentially",
    )


# ---------------------------------------------------------------------------
# Approve plan — release the run-all gate before remediation_executor runs
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/plan/approve",
    response_model=SidebarState,
)
async def approve_plan(workspace_id: str, request: Request, db=Depends(get_db)):
    """Mark the workspace's remediation plan as approved.

    PRD-0006 Story 3 — the planner pauses the run-all loop until the user
    explicitly approves. This endpoint flips ``plan.approved=true`` in BOTH
    stores: the SQLite sidebar (read by the Issues-page derivation) AND
    the filesystem ``context/plan.json`` (read by ``suggest_next`` to
    decide whether the executor may run). A subsequent
    ``POST /pipeline/run-all`` will then suggest the executor.

    Returns 404 if the workspace doesn't exist or the planner hasn't yet
    written a plan to the sidebar.
    """
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    context_builder = request.app.state.context_builder
    plan = await context_builder.mark_plan_approved(db, workspace_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="No plan to approve — has the planner finished?",
        )
    sidebar = await get_sidebar(db, workspace_id)
    return sidebar


# ---------------------------------------------------------------------------
# Cancel running agent
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/cancel",
    status_code=200,
)
async def cancel_agent_run(
    workspace_id: str,
    run_id: str,
    db=Depends(get_db),
):
    """Cancel a running agent run."""
    run = await get_agent_run(db, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != "running":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel agent run with status '{run.status}'",
        )

    await update_agent_run(
        db, run_id, AgentRunUpdate(status="cancelled")
    )
    return {"status": "cancelled", "agent_run_id": run_id}


# ---------------------------------------------------------------------------
# Permission approval
# ---------------------------------------------------------------------------


class PermissionDecision(BaseModel):
    approved: bool


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/permission",
    status_code=200,
)
async def respond_to_permission(
    workspace_id: str,
    run_id: str,
    body: PermissionDecision,
    request: Request,
):
    """Approve or deny a pending tool-use permission request."""
    executor = request.app.state.agent_executor

    resolved = (
        executor.approve_tool(run_id)
        if body.approved
        else executor.deny_tool(run_id)
    )

    if not resolved:
        raise HTTPException(
            status_code=404,
            detail="No pending permission request for this agent run",
        )

    return {
        "status": "approved" if body.approved else "denied",
        "agent_run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Agent execution SSE stream
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/agent-execution/stream")
async def stream_agent_execution(
    workspace_id: str,
    request: Request,
):
    """Stream permission_request and done events during agent execution.

    The frontend connects to this while an agent is running. Events:
    - permission_request: agent needs user approval for a tool
    - done: agent execution has completed (success or failure)

    If the client disconnects while a permission is pending, the pending
    approval is auto-denied to unblock the executor.
    """
    executor = request.app.state.agent_executor

    async def event_generator():
        queue = executor.get_permission_queue(workspace_id)
        if not queue:
            # No active execution — send done immediately
            yield {"event": "done", "data": "{}"}
            return

        try:
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    # Auto-deny any pending approval to unblock executor
                    run_id = executor.get_active_run_id(workspace_id)
                    if run_id:
                        executor.deny_tool(run_id)
                        logger.info(
                            "Client disconnected, auto-denied permission "
                            "for workspace %s run %s",
                            workspace_id, run_id,
                        )
                    return

                # Poll queue with timeout to allow disconnect checks
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2.0)
                except TimeoutError:
                    continue

                event_type = event.get("type", "permission_request")
                if event_type == "done":
                    yield {"event": "done", "data": "{}"}
                    return
                else:
                    yield {
                        "event": "permission_request",
                        "data": json.dumps({
                            "id": event.get("id", ""),
                            "tool": event.get("tool", "unknown"),
                            "patterns": event.get("patterns", []),
                            "run_id": event.get("run_id", ""),
                        }),
                    }
        except Exception:
            logger.exception(
                "Error in agent execution stream for workspace %s",
                workspace_id,
            )
            yield {
                "event": "error",
                "data": json.dumps({"message": "Stream disconnected"}),
            }

    return EventSourceResponse(event_generator())
