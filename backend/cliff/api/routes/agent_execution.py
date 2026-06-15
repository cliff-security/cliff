"""Agent execution endpoints — trigger, stream, cancel, suggest-next."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cliff.agents.errors import AgentBusyError, AgentProcessError
from cliff.agents.pipeline import VALID_AGENT_TYPES, suggest_next
from cliff.agents.triage_runner import run_triage
from cliff.api.routes.workspaces import _resolve_github_repo_url, _resolve_repo_env_vars
from cliff.db.connection import get_db
from cliff.db.repo_agent_run import get_agent_run, update_agent_run
from cliff.db.repo_finding import get_finding
from cliff.db.repo_sidebar import get_sidebar
from cliff.db.repo_workspace import get_workspace, list_workspaces
from cliff.integrations.github_app.client import check_repo_push_access
from cliff.models import AgentRunUpdate, SidebarState

# Surface link the IssueSidePanel and 412 error body point at when the
# device-flow token lacks push access. Kept as a module-level constant so
# the frontend and docs guide can stay in sync via a single edit. Refs
# ADR-0037 / IMPL-0014 / B30.
# Absolute GitHub-hosted URL because (a) the Cliff backend does not serve
# the ``docs/`` tree, and (b) browsers won't render ``.md`` files as HTML
# even if it did — GitHub's renderer is what makes the link useful at
# all. Kept in sync with the duplicate constants in
# ``frontend/src/components/issues/IssueSidePanel.tsx`` and
# ``frontend/src/components/settings/PushAccessBadge.tsx`` (single edit
# touches all three).
GITHUB_APP_PERMS_DOC_URL = (
    "https://github.com/cliff-security/cliff/blob/main/"
    "docs/guides/setup-github-app.md#required-permissions"
)

# The single agent type that actually needs to push to GitHub. Other
# agents read context, talk to the LLM, write files locally — they do
# not need a write-capable token. Gating only this agent keeps the
# preflight off the hot path for the 90% of executions that don't care.
_PUSH_GATED_AGENT_TYPE = "remediation_executor"

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


def _parse_owner_repo_from_url(repo_url: str) -> tuple[str, str] | None:
    """Parse ``owner/repo`` out of a github HTTPS URL.

    Tolerates a trailing ``.git`` and any extra path segments. Returns
    ``None`` for anything that doesn't look like a GitHub repo URL — the
    caller treats that as "skip the preflight" rather than as a failure,
    because non-GitHub remotes are out of scope for this gate.

    Security: uses ``urlparse`` and an exact ``hostname == "github.com"``
    check (not a substring / endswith). This rejects bypass attempts like
    ``https://attacker.com/github.com/owner/repo`` (github.com in path) and
    ``https://github.com.attacker.com/owner/repo`` (github.com as a subdomain
    prefix of an attacker domain). See CodeQL rule
    py/incomplete-url-substring-sanitization.
    """
    if not isinstance(repo_url, str) or not repo_url:
        return None
    try:
        parsed = urlparse(repo_url)
    except ValueError:
        return None
    # Exact hostname match — case-insensitive per RFC 3986 (urlparse already
    # lowercases ``hostname``). Reject anything without an https scheme so a
    # crafted ``javascript:`` or ``file://`` URL can't slip through.
    if parsed.scheme not in ("https", "http"):
        return None
    if parsed.hostname != "github.com":
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return None
    return owner, name


@router.get("/agents/chips", response_model=list[AgentChipResponse])
async def list_agent_chips():
    """Return the ordered list of action chips for the UI."""
    from cliff.agents.registry import AGENT_CHIPS

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

    # Resolve GitHub env vars (GH_TOKEN, CLIFF_REPO_URL) for the workspace process.
    # Pass the workspace so the snapshotted repo URL wins over the live integration.
    env_vars = await _resolve_repo_env_vars(request, db, workspace=workspace)
    user_note = body.user_note if body else None

    # Q01R / B30 / ADR-0037: preflight push access ONLY for the executor.
    # The other agents don't push — gating them would waste a GitHub
    # API call and slow down enrich / plan / etc. If the token or repo
    # URL is missing we skip the check and let the executor's own
    # missing-token error path handle it (already clear).
    if (
        agent_type == _PUSH_GATED_AGENT_TYPE
        and env_vars.get("GH_TOKEN")
        and env_vars.get("CLIFF_REPO_URL")
    ):
        owner_repo = _parse_owner_repo_from_url(env_vars["CLIFF_REPO_URL"])
        if owner_repo is not None:
            owner, repo = owner_repo
            access = await check_repo_push_access(
                token=env_vars["GH_TOKEN"],
                owner=owner,
                repo=repo,
            )
            if not access.can_push:
                raise HTTPException(
                    status_code=412,
                    detail={
                        "error": "github_app_permissions",
                        "reason": access.reason,
                        "remediation_link": GITHUB_APP_PERMS_DOC_URL,
                    },
                )

    # Launch execution as a background task so we can return immediately.
    async def _run_in_background() -> None:
        try:
            await executor.execute(
                workspace_id,
                agent_type,
                db,
                workspace_dir=workspace.workspace_dir,
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

    # The Plan gate (ADR-0051 §6 / ADR-0054): a finding triaged as *not real*
    # never gets a remediation plan — clearing noise with reasoning is the
    # product's value, and an alarmist plan on a non-reachable finding is a
    # false-positive-shaped result. The CLI (`cliffsec fix`) gates on the
    # verdict before it ever calls run-all; this is the server-side backstop so
    # NO caller (web, API) can drive the planner on noise. Defence-in-depth, so
    # it is intentionally narrow: it engages only when triage has run AND
    # returned a non-real verdict AND there is no human-approved plan overriding
    # it. A finding that was never triaged behaves exactly as before.
    sidebar = await get_sidebar(db, workspace_id)
    triage = sidebar.triage if sidebar and isinstance(sidebar.triage, dict) else None
    # Gate only on a CONCRETE non-real verdict. A missing/partial triage write
    # ({} or no ``verdict``) leaves ``verdict`` empty and falls through to the
    # normal pipeline — only a real dismissal/needs_review verdict blocks the
    # planner, so an in-flight or never-triaged finding behaves as before.
    verdict = (triage.get("verdict") or "").lower() if triage else ""
    if verdict and verdict != "real":
        # ...but a HUMAN can override a non-real verdict. The web "Looks real —
        # remediate" action confirms the finding by advancing its status to
        # ``triaged`` (ADR-0051 §6 — ``triaged`` means "confirmed real") BEFORE
        # firing run-all; an already-approved plan is the same signal. Only an
        # unconfirmed finding still sitting at ``new`` with a non-real verdict is
        # blocked, so the gate stops auto-planning on noise without breaking the
        # human confirm-real path. (The CLI `real` path passes the verdict check
        # above and never reaches here.)
        finding = await get_finding(db, workspace.finding_id)
        human_confirmed = finding is not None and finding.status != "new"
        plan_approved = bool((sidebar.plan or {}).get("approved")) if sidebar else False
        if not human_confirmed and not plan_approved:
            logger.info(
                "run-all gated for workspace %s: triaged %r, finding still new — no plan",
                workspace_id,
                verdict,
            )
            return RunAllResponse(
                status="gated",
                message=(
                    f"Triaged as {verdict} — no remediation plan needed. "
                    f"Confirm it's real to plan a fix."
                ),
            )

    try:
        await executor.check_not_busy(db, workspace_id)
    except AgentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    env_vars = await _resolve_repo_env_vars(request, db, workspace=workspace)

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
                    result = await executor.execute(
                        workspace_id,
                        agent_type,
                        db,
                        workspace_dir=workspace.workspace_dir,
                        env_vars=env_vars,
                    )
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
                    continue

                # ``executor.execute`` swallows ``AgentProcessError`` (and the
                # generic ``Exception`` path) and returns ``status='failed'``
                # / ``'rate_limited'`` instead of re-raising — so the except
                # block above will not fire for LLM-side failures (out of
                # credits, parse errors, upstream 429 after the in-executor
                # backoff is exhausted, etc). Without this check the loop
                # kept retrying the same failing agent ``max_iterations``
                # times, burning credits and producing 10+ duplicate failed
                # ``agent_run`` rows per workspace. Mirror the contract of
                # ``pipeline.run_pipeline`` and break immediately on a
                # non-success status.
                if result.status in ("failed", "rate_limited"):
                    logger.warning(
                        "Pipeline stopped: %s ended status=%s for workspace %s",
                        agent_type,
                        result.status,
                        workspace_id,
                    )
                    break

                consecutive_failures = 0
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
# Run triage (ADR-0051 / PRD-0008)
# ---------------------------------------------------------------------------


class TriageRunResponse(BaseModel):
    workspace_id: str
    status: str


@router.post(
    "/findings/{finding_id}/triage",
    response_model=TriageRunResponse,
    status_code=202,
)
async def run_triage_endpoint(
    finding_id: str,
    request: Request,
    db=Depends(get_db),
):
    """Run triage on a finding as a background task (ADR-0051 / PRD-0008).

    Ensures a workspace for the finding WITHOUT advancing its status (triage
    keeps the finding ``new`` until a `real` verdict is confirmed — the Plan
    gate, ADR-0051 §6), then runs ``enricher → exposure → synthesis`` for a
    scanner finding or ``report_triager`` for a report. Poll
    ``GET /workspaces/{workspace_id}/sidebar`` for the verdict.

    Note (deviation from IMPL-0024 §3.2's ``POST /workspaces/{id}/triage``):
    triage is finding-scoped because it must create a *non-status-advancing*
    workspace — a workspace-scoped path would require the workspace to already
    exist, and creating it via the standard remediation path flips the finding
    to ``in_progress``, defeating the gate.
    """
    finding = await get_finding(db, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")

    executor = request.app.state.agent_executor
    context_builder = request.app.state.context_builder

    # Ensure a workspace — reuse the one-per-finding workspace if present, else
    # create one without advancing the finding's status.
    existing = await list_workspaces(db, finding_id=finding_id, limit=1)
    if existing:
        workspace = existing[0]
        if not workspace.workspace_dir:
            # A stale/partial workspace row (no directory) would otherwise
            # return 202 and fail only in the background. Surface it now.
            raise HTTPException(
                status_code=400, detail="Workspace has no directory"
            )
    else:
        repo_url = await _resolve_github_repo_url(db)
        workspace = await context_builder.create_workspace(
            db, finding, repo_url=repo_url, advance_status=False
        )

    try:
        await executor.check_not_busy(db, workspace.id)
    except AgentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    env_vars = await _resolve_repo_env_vars(request, db, workspace=workspace)
    # Canonical AI state (ADR-0037) — enables the agentic Deep dive on
    # escalation (ADR-0052); absent it, triage stays the cheap Quick read.
    ai_env = dict(getattr(request.app.state, "ai_env_cache", {}) or {})
    ai_model = getattr(request.app.state, "ai_model_cache", None)

    async def _run_in_background() -> None:
        try:
            await run_triage(
                executor,
                db,
                workspace,
                env_vars=env_vars,
                ai_env=ai_env,
                model_full_id=ai_model,
            )
        except (AgentBusyError, AgentProcessError):
            logger.exception("Triage failed for workspace %s", workspace.id)
        except Exception:
            logger.exception(
                "Unexpected error in background triage for workspace %s", workspace.id
            )

    asyncio.create_task(_run_in_background())

    return TriageRunResponse(workspace_id=workspace.id, status="running")


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
    deny_message: str | None = None


@router.post(
    "/workspaces/{workspace_id}/agent-runs/{run_id}/permission",
    status_code=200,
)
async def respond_to_permission(
    workspace_id: str,
    run_id: str,
    body: PermissionDecision,
    request: Request,
    db=Depends(get_db),
):
    """Approve or deny a paused executor tool call, resuming the run.

    ADR-0047 / PR #2 — the remediation_executor pauses on a gated tool by
    persisting a ``DeferredToolRequests`` marker (``agent_run.permission_
    request`` + ``pa_message_history``). This endpoint resumes the run via
    ``executor.resume_executor`` with the user's decision. Resume actually
    re-runs the agent (it can take minutes), so it runs as a background
    task and returns immediately — the frontend polls ``agent-runs`` for
    the outcome (no SSE).
    """
    executor = request.app.state.agent_executor

    run = await get_agent_run(db, run_id)
    if run is None or run.workspace_id != workspace_id or not run.permission_pending:
        raise HTTPException(
            status_code=404,
            detail="No pending permission request for this agent run",
        )
    workspace = await get_workspace(db, workspace_id)
    if workspace is None or not workspace.workspace_dir:
        raise HTTPException(status_code=404, detail="Workspace not found")

    env_vars = await _resolve_repo_env_vars(request, db, workspace=workspace)

    async def _resume_in_background() -> None:
        try:
            await executor.resume_executor(
                db,
                workspace_id,
                run_id,
                approved=body.approved,
                workspace_dir=workspace.workspace_dir,
                deny_message=body.deny_message,
                env_vars=env_vars,
            )
        except Exception:
            logger.exception(
                "Resume after permission decision failed for run %s", run_id
            )

    asyncio.create_task(_resume_in_background())

    return {
        "status": "approved" if body.approved else "denied",
        "agent_run_id": run_id,
    }

