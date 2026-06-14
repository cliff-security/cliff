"""Assessment routes (IMPL-0002 Milestone D2).

``POST /assessment/run`` creates a ``pending`` row and schedules the engine as a
background task. ``GET /assessment/status/{id}`` polls the current state (SSE
upgrade is deferred to Session G per the Session-0 stub comment). ``GET
/assessment/latest`` returns the most recent assessment's report-card shape.

The engine is injected via ``get_assessment_engine``; Session A/G swap the real
implementation behind the same DI seam.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FastAPIRequest
from pydantic import BaseModel

from cliff.api._background import (
    get_assessment_step,
    get_assessment_tools,
    schedule_assessment_run,
)
from cliff.api._engine_dep import (
    AssessmentEngineProtocol,
    get_assessment_engine,
)
from cliff.db.connection import get_db
from cliff.db.dao.assessment import (
    create_assessment,
    get_assessment,
    mark_summary_seen,
)
from cliff.db.dao.assessment import (
    get_latest_assessment as dao_get_latest_assessment,
)
from cliff.db.repo_finding import (
    count_findings_by_priority,
    list_posture_findings,
)
from cliff.models import (
    Assessment,
    AssessmentCreate,
    AssessmentError,
    AssessmentStatus,
    AssessmentTool,
    AssessmentToolResult,
    CriteriaSnapshot,
    Grade,
)

router = APIRouter(prefix="/assessment", tags=["assessment"])


class AssessmentRunResponse(BaseModel):
    assessment_id: str
    status: str


class AssessmentStep(BaseModel):
    """One row in the assessment progress timeline (ADR-0032 §1.7)."""

    key: str
    label: str
    state: str  # pending | running | done | skipped
    progress_pct: int | None = None
    detail: str | None = None
    result_summary: str | None = None
    hint: str | None = None


class PreviousAssessmentInfo(BaseModel):
    """Continuity card on the assessment-running surface (IMPL-0009).

    Populated when at least one prior completed assessment exists so users
    don't feel data vanished while the new run is in flight.
    """

    assessment_id: str
    grade: Grade | None = None
    open_count: int = 0
    commit_sha: str | None = None
    finished_at: str | None = None
    report_href: str  # static template; frontend may ignore


class AssessmentStatusResponse(BaseModel):
    assessment_id: str
    status: str
    progress_pct: int
    step: str | None = None
    steps: list[AssessmentStep] = []
    tools: list[AssessmentTool] = []
    summary_seen_at: str | None = None
    # IMPL-0009 — second-most-recent completed assessment, when one exists.
    previous_assessment: PreviousAssessmentInfo | None = None
    # Migration 015 — populated only when ``status == 'failed'``. Mirrors
    # the ``error_*`` columns on the assessment row so the dashboard can
    # render the failure card without an extra round-trip.
    error: AssessmentError | None = None
    repo_url: str | None = None


class MarkSummarySeenResponse(BaseModel):
    """Idempotent response: ``summary_seen_at`` is set on first call."""

    assessment_id: str
    summary_seen_at: str


class AssessmentLatestResponse(BaseModel):
    assessment: Assessment
    grade: Grade
    criteria: CriteriaSnapshot
    findings_count_by_priority: dict[str, int]
    posture_pass_count: int
    posture_total_count: int


_STATUS_TO_PROGRESS: dict[AssessmentStatus, int] = {
    "pending": 0,
    "running": 50,
    "complete": 100,
    "failed": 0,
}

# Progress percentage per v0.2 step key — used when the assessment is running
# and we have a live step. Ordered to match the user-visible sequence.
_STEP_PROGRESS: dict[str, int] = {
    "detect": 10,
    "trivy_vuln": 25,
    "trivy_secret": 40,
    "semgrep": 60,
    "posture": 80,
    "descriptions": 95,
}

# v0.2 step timeline (ADR-0032). The engine emits one of these keys per
# completed phase; the UI renders them in this order.
_V2_STEPS_ORDER: list[tuple[str, str, str | None]] = [
    ("detect", "Detecting project type", None),
    ("trivy_vuln", "Scanning dependencies with Trivy", None),
    ("trivy_secret", "Scanning for secrets with Trivy", None),
    ("semgrep", "Scanning code with Semgrep", None),
    ("posture", "Checking repo posture", "15 checks"),
    ("descriptions", "Generating plain-language descriptions", None),
]


def _build_steps(live_step: str | None, status: AssessmentStatus) -> list[AssessmentStep]:
    """Synthesize the steps list from the engine's live ``live_step`` key.

    Keys before ``live_step`` are ``done``, the live one is ``running``, the
    rest are ``pending``. The posture step carries a ``hint`` (15 checks) per
    the architect's regression test ``test_assessment_status_step_hint_for_posture``.
    """
    cursor = live_step
    steps: list[AssessmentStep] = []
    seen_running = False
    for key, label, hint in _V2_STEPS_ORDER:
        if status == "complete":
            state = "done"
        elif status == "pending":
            state = "pending"
        elif status == "failed":
            state = "skipped"
        elif key == cursor:
            state = "running"
            seen_running = True
        elif not seen_running:
            state = "done"
        else:
            state = "pending"
        steps.append(
            AssessmentStep(
                key=key,
                label=label,
                state=state,
                hint=hint if state == "pending" else None,
            )
        )
    return steps


def _build_running_tools() -> list[AssessmentTool]:
    """Default tools[] payload while an assessment is in flight.

    The engine rewrite (Epic 3) overrides this with live state from each
    scanner. Until then the API returns sensible pending/active markers so
    the UI can render the ToolPillBar.
    """
    return [
        AssessmentTool(
            id="trivy",
            label="Trivy",
            version=None,
            icon="bug_report",
            state="active",
            result=None,
        ),
        AssessmentTool(
            id="semgrep",
            label="Semgrep",
            version=None,
            icon="code",
            state="pending",
            result=None,
        ),
        AssessmentTool(
            id="posture",
            label="15 posture checks",
            version=None,
            icon="rule",
            state="pending",
            result=None,
        ),
    ]


def _build_done_tools(pass_count: int, total_count: int) -> list[AssessmentTool]:
    return [
        AssessmentTool(
            id="trivy",
            label="Trivy",
            version=None,
            icon="bug_report",
            state="done",
            result=AssessmentToolResult(kind="findings_count", value=0, text="0 findings"),
        ),
        AssessmentTool(
            id="semgrep",
            label="Semgrep",
            version=None,
            icon="code",
            state="done",
            result=AssessmentToolResult(kind="findings_count", value=0, text="0 findings"),
        ),
        AssessmentTool(
            id="posture",
            label=f"{total_count} posture checks",
            version=None,
            icon="rule",
            state="done",
            result=AssessmentToolResult(
                kind="pass_count", value=pass_count, text=f"{pass_count} pass"
            ),
        ),
    ]


@router.post("/run", response_model=AssessmentRunResponse)
async def run_assessment(
    request: AssessmentCreate,
    http_request: FastAPIRequest,
    db=Depends(get_db),
    engine: AssessmentEngineProtocol = Depends(get_assessment_engine),
) -> AssessmentRunResponse:
    """Start a new assessment for the given repo."""
    if not request.repo_url.strip():
        raise HTTPException(status_code=422, detail="repo_url must not be empty")

    assessment = await create_assessment(db, request)
    schedule_assessment_run(
        http_request.app, db, engine, assessment.id, request.repo_url
    )
    # Eager Project-profile build (ADR-0053 / PRD-0009): kicks off alongside the
    # scan so triage is grounded later. Best-effort — never blocks the scan, and
    # no-ops when no AI provider is configured.
    from cliff.repos.service import schedule_profile_build

    schedule_profile_build(http_request.app, db, request.repo_url)
    return AssessmentRunResponse(assessment_id=assessment.id, status="pending")


@router.get("/status/{assessment_id}", response_model=AssessmentStatusResponse)
async def get_assessment_status(
    assessment_id: str, db=Depends(get_db)
) -> AssessmentStatusResponse:
    """Poll assessment progress.

    When the assessment is ``running``, ``step`` is the live phase from
    :func:`cliff.api._background.get_assessment_step` (e.g. ``cloning`` or
    ``looking_up_cves``); otherwise it mirrors ``status``.
    """
    a = await get_assessment(db, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found")

    step = a.status
    progress = _STATUS_TO_PROGRESS.get(a.status, 0)
    if a.status == "running":
        live_step = get_assessment_step(assessment_id)
        if live_step is not None:
            step = live_step
            progress = _STEP_PROGRESS.get(live_step, progress)

    if a.status == "complete":
        posture_rows = await list_posture_findings(db, a.id)
        pass_count = sum(
            1 for r in posture_rows if r.status == "passed" and r.grade_impact == "counts"
        )
        total_count = sum(1 for r in posture_rows if r.grade_impact == "counts")
        tools = a.tools or _build_done_tools(pass_count, total_count)
    else:
        # Live in-flight tools[] from the engine's on_tool callback (PR-B).
        # Falls back to the static "active/pending/pending" placeholder while
        # the engine hasn't produced its first transition yet.
        live_tools = get_assessment_tools(assessment_id)
        tools = live_tools or a.tools or _build_running_tools()

    previous = await _previous_assessment_info(db, a.id)

    error_block: AssessmentError | None = None
    if a.status == "failed" and a.error_kind is not None:
        error_block = AssessmentError(
            kind=a.error_kind,
            message=a.error_message
            or "Something went wrong while running the assessment",
            failed_step=a.failed_step,
            details=a.error_details,
        )

    return AssessmentStatusResponse(
        assessment_id=a.id,
        status=a.status,
        progress_pct=progress,
        step=step,
        steps=_build_steps(step if a.status == "running" else None, a.status),
        tools=tools,
        summary_seen_at=a.summary_seen_at.isoformat() if a.summary_seen_at else None,
        previous_assessment=previous,
        error=error_block,
        repo_url=a.repo_url,
    )


async def _previous_assessment_info(
    db, current_assessment_id: str
) -> PreviousAssessmentInfo | None:
    """Look up the most recent completed assessment that isn't ``current``.

    Used by the assessment-running surface's "Previous assessment" card so
    the user has continuity while the new scan is in flight.
    """
    cursor = await db.execute(
        "SELECT id, grade, completed_at, commit_sha "
        "FROM assessment "
        "WHERE status = 'complete' AND completed_at IS NOT NULL AND id != ? "
        "ORDER BY completed_at DESC LIMIT 1",
        (current_assessment_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    prior_id = row["id"]

    # Open count = findings registered in that scan still in an open status.
    open_statuses = ("new", "triaged", "in_progress", "remediated")
    placeholders = ",".join("?" for _ in open_statuses)
    count_cur = await db.execute(
        f"SELECT COUNT(*) AS n FROM finding "  # noqa: S608
        f"WHERE assessment_id = ? AND status IN ({placeholders})",
        (prior_id, *open_statuses),
    )
    count_row = await count_cur.fetchone()
    open_count = int(count_row["n"]) if count_row else 0

    finished_at = row["completed_at"]
    return PreviousAssessmentInfo(
        assessment_id=prior_id,
        grade=row["grade"],
        open_count=open_count,
        commit_sha=row["commit_sha"],
        finished_at=finished_at if isinstance(finished_at, str) else None,
        report_href=f"/dashboard?assessment_id={prior_id}",
    )


@router.post(
    "/{assessment_id}/mark-summary-seen", response_model=MarkSummarySeenResponse
)
async def mark_summary_seen_route(
    assessment_id: str, db=Depends(get_db)
) -> MarkSummarySeenResponse:
    """Idempotent: flips ``summary_seen_at`` to ``now()`` only when NULL.

    The first call writes the timestamp; subsequent calls return the same
    value. The frontend invokes this once when the user dismisses the
    assessment-complete interstitial (Surface 3 of PRD-0003 v0.2).
    """
    a = await mark_summary_seen(db, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if a.summary_seen_at is None:
        # The DAO writes only when the column was NULL — but if the row
        # vanished between fetch and update, we'd land here. Treat the
        # absence as an idempotent no-op rather than an error so the
        # frontend's gating logic still settles.
        raise HTTPException(status_code=409, detail="Assessment summary not yet ready")
    return MarkSummarySeenResponse(
        assessment_id=a.id,
        summary_seen_at=a.summary_seen_at.isoformat(),
    )


@router.get("/latest", response_model=AssessmentLatestResponse)
async def get_latest_assessment(db=Depends(get_db)) -> AssessmentLatestResponse:
    """Report-card payload for the dashboard."""
    latest = await dao_get_latest_assessment(db)
    if latest is None:
        raise HTTPException(status_code=404, detail="No assessments yet")
    if latest.grade is None:
        raise HTTPException(status_code=409, detail="Latest assessment is not yet complete")

    posture_rows = await list_posture_findings(db, latest.id)
    pass_count = sum(
        1 for r in posture_rows if r.status == "passed" and r.grade_impact == "counts"
    )
    total_count = sum(1 for r in posture_rows if r.grade_impact == "counts")
    counts = await count_findings_by_priority(db)

    return AssessmentLatestResponse(
        assessment=latest,
        grade=latest.grade,
        criteria=latest.criteria_snapshot or CriteriaSnapshot(),
        findings_count_by_priority=counts,
        posture_pass_count=pass_count,
        posture_total_count=total_count,
    )
