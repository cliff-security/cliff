"""Background orchestration for assessment runs (PRD-0003 v0.2 / IMPL-0003-p2).

Both ``/api/assessment/run`` and ``/api/onboarding/repo`` need to kick off an
engine run without blocking the response. This module owns:

  * ``run_and_persist_assessment`` — the single coroutine that drives the
    engine and finalises the assessment row. The engine itself persists every
    finding (Trivy / Semgrep / posture) via the unified UPSERT in Phase 2;
    this module only updates the assessment row's status, tools_json, grade,
    and criteria_snapshot, plus opens a completion row when the user hits
    Grade A.
  * ``schedule_assessment_run`` — fires the coroutine as a task tracked in
    ``app.state.assessment_tasks`` and self-evicts on completion.

Per-assessment in-memory state (``_ASSESSMENT_STEPS`` / ``_ASSESSMENT_TOOLS``)
backs the live ToolPillBar in the running-state UI; the durable signals are
the assessment row's ``status`` and ``tools_json``.

Migration 015 wired the failure path to persist ``error_kind`` /
``error_message`` / ``error_details`` / ``failed_step``. The engine never
finishing is bounded two ways:

  * Each ``run_and_persist_assessment`` call is wrapped in
    ``asyncio.timeout(ASSESSMENT_RUN_TIMEOUT_S)`` so a hang inside posture
    checks or DB persist still terminates within ~10 minutes.
  * A separate watchdog loop in :mod:`opensec.main` reaps any
    ``pending``/``running`` row older than ``ASSESSMENT_STALE_THRESHOLD_S``,
    covering the race where this task was enqueued but the event loop never
    ran it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from opensec.assessment.clone import CloneError, CloneTimeoutError
from opensec.assessment.scanners.runner import ScannerTimeoutError
from opensec.db.dao.assessment import set_assessment_result, update_assessment
from opensec.db.dao.completion import (
    create_completion,
    get_completion_for_assessment,
)
from opensec.models import (
    AssessmentErrorKind,
    AssessmentFailedStep,
    AssessmentTool,
    AssessmentUpdate,
    CompletionCreate,
)

if TYPE_CHECKING:
    import aiosqlite
    from fastapi import FastAPI

    from opensec.api._engine_dep import AssessmentEngineProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- safety net

#: Hard upper bound on a single assessment run. Per-step timeouts in the
#: engine cap clone/Trivy/Semgrep individually, but posture checks and
#: post-clone DB persistence are unbounded. 10 minutes comfortably exceeds
#: the slowest healthy run (~3 min) while still bounding worst-case wedges.
ASSESSMENT_RUN_TIMEOUT_S: float = 600.0

#: Maximum truncated length of the captured error detail. Trivy and git can
#: emit multi-megabyte error blobs; the UI only renders the head, and we
#: don't want a runaway error to bloat the SQLite row.
_ERROR_DETAILS_MAX_CHARS: int = 4_000


_ASSESSMENT_STEPS: dict[str, str] = {}
_ASSESSMENT_TOOLS: dict[str, dict[str, AssessmentTool]] = {}


def get_assessment_step(assessment_id: str) -> str | None:
    """Current phase for an in-flight assessment, or ``None`` if unknown."""
    return _ASSESSMENT_STEPS.get(assessment_id)


def get_assessment_tools(assessment_id: str) -> list[AssessmentTool] | None:
    """Live ``tools[]`` payload for an in-flight assessment, or ``None``."""
    pills = _ASSESSMENT_TOOLS.get(assessment_id)
    if pills is None:
        return None
    return list(pills.values())


# ---------------------------------------------------------------- classifier


_VALID_FAILED_STEPS: frozenset[str] = frozenset(
    {
        "clone",
        "detect",
        "trivy_vuln",
        "trivy_secret",
        "semgrep",
        "posture",
        "descriptions",
        "persist",
        "unknown",
    }
)


def classify_assessment_failure(
    exc: BaseException, *, live_step: str | None
) -> tuple[AssessmentErrorKind, str, AssessmentFailedStep]:
    """Map an exception + live engine step to (kind, friendly_message, step).

    The friendly message is the headline the dashboard renders. The
    ``failed_step`` is what the engine was doing at the moment of failure;
    the frontend turns it into copy like "while cloning the repository".

    Pure helper so unit tests can assert the mapping without standing up the
    whole runner.
    """
    if isinstance(exc, CloneTimeoutError | CloneError):
        return (
            "clone_failed",
            "Couldn't clone the repository",
            "clone",
        )

    step = _coerce_failed_step(live_step)

    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        # The asyncio outer timeout fires as ``TimeoutError`` (3.11+); the
        # inner ``ScannerTimeoutError`` is a separate class declared in
        # ``scanners/runner.py``. Both surface as the same friendly kind so
        # the user sees one consistent "took too long" headline.
        return (
            "timeout",
            "The assessment took too long to finish",
            step,
        )

    if isinstance(exc, ScannerTimeoutError):
        return (
            "timeout",
            "A scanner took too long to finish",
            step,
        )

    if isinstance(exc, ValueError):
        # ``shallow_clone`` raises ValueError for malformed URLs;
        # ``_coords_from_repo_url`` raises it for un-parseable owner/repo.
        return (
            "internal_error",
            "The repository URL is invalid",
            step,
        )

    if isinstance(exc, FileNotFoundError):
        # ``asyncio.create_subprocess_exec`` raises this when the scanner
        # binary isn't on disk. Without a special branch the user sees a
        # generic "Something went wrong" headline and has to expand the
        # technical-details disclosure to learn that ``trivy`` is missing
        # — which is one of the most actionable failure modes we have
        # (run scripts/install-scanners.sh and you're back). Surface it
        # at the headline level.
        missing = (
            exc.filename
            or _missing_binary_from_message(str(exc))
            or _binary_for_step(step)
        )
        if missing:
            headline = (
                f"Scanner binary {missing!r} is missing — re-run "
                f"scripts/install-scanners.sh"
            )
        else:
            headline = (
                "A scanner binary is missing — re-run "
                "scripts/install-scanners.sh"
            )
        return ("internal_error", headline, step)

    return (
        "internal_error",
        "Something went wrong while running the assessment",
        step,
    )


def _missing_binary_from_message(message: str) -> str | None:
    """Best-effort extract of the missing-binary name from a FileNotFoundError.

    ``asyncio.create_subprocess_exec`` may raise
    ``FileNotFoundError(2, 'No such file or directory')`` *without* a
    ``filename`` attribute set (Linux + uvloop on some glibc versions);
    in that case the only signal is the message text. Returns ``None``
    when nothing useful can be parsed.
    """
    import re

    match = re.search(r"['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else None


# Map an engine step back to the scanner binary it was about to launch.
# Last-resort source of truth when ``FileNotFoundError`` carries neither
# a ``filename`` attribute nor a parseable message body.
_STEP_TO_BINARY: dict[AssessmentFailedStep, str] = {
    "trivy_vuln": "trivy",
    "trivy_secret": "trivy",
    "semgrep": "semgrep",
}


def _binary_for_step(step: AssessmentFailedStep) -> str | None:
    return _STEP_TO_BINARY.get(step)


def _coerce_failed_step(value: str | None) -> AssessmentFailedStep:
    """Map a free-form live-step string to a known ``AssessmentFailedStep``."""
    if value in _VALID_FAILED_STEPS:
        return value  # type: ignore[return-value]
    return "unknown"


def _truncate_details(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) <= _ERROR_DETAILS_MAX_CHARS:
        return text
    cut = text[:_ERROR_DETAILS_MAX_CHARS].rstrip()
    return f"{cut}\n... (truncated, full message in server logs)"


# ---------------------------------------------------------------- runner


async def run_and_persist_assessment(
    db: aiosqlite.Connection,
    engine: AssessmentEngineProtocol,
    assessment_id: str,
    repo_url: str,
    *,
    timeout_s: float = ASSESSMENT_RUN_TIMEOUT_S,
) -> None:
    """Drive the engine for one assessment and finalise the assessment row."""

    async def _on_step(step: str) -> None:
        _ASSESSMENT_STEPS[assessment_id] = step

    async def _on_tool(tool: AssessmentTool) -> None:
        pills = _ASSESSMENT_TOOLS.setdefault(assessment_id, {})
        pills[tool.id] = tool

    try:
        await update_assessment(db, assessment_id, AssessmentUpdate(status="running"))
        _ASSESSMENT_STEPS[assessment_id] = "detect"
        async with asyncio.timeout(timeout_s):
            result = await engine.run_assessment(
                repo_url,
                assessment_id=assessment_id,
                db=db,
                on_step=_on_step,
                on_tool=_on_tool,
            )
    except asyncio.CancelledError:
        # Process is shutting down. Mark the row interrupted so the next boot
        # doesn't have to rely solely on the startup reconciliation, then
        # re-raise so cancellation semantics propagate cleanly to the task
        # group.
        await _persist_failure(
            db,
            assessment_id,
            kind="interrupted",
            message="Assessment was interrupted (the server is shutting down)",
            failed_step=_coerce_failed_step(_ASSESSMENT_STEPS.get(assessment_id)),
            details=None,
        )
        _clear_in_memory_state(assessment_id)
        raise
    except Exception as exc:
        live_step = _ASSESSMENT_STEPS.get(assessment_id)
        kind, message, failed_step = classify_assessment_failure(
            exc, live_step=live_step
        )
        logger.exception(
            "assessment %s failed: kind=%s step=%s",
            assessment_id,
            kind,
            failed_step,
        )
        await _persist_failure(
            db,
            assessment_id,
            kind=kind,
            message=message,
            failed_step=failed_step,
            details=_truncate_details(str(exc) or exc.__class__.__name__),
        )
        _clear_in_memory_state(assessment_id)
        return

    # Persist final tools[] + grade + criteria. Findings + posture rows are
    # already in the unified ``finding`` table (engine handled it); this
    # finalises the assessment metadata.
    await update_assessment(
        db, assessment_id, AssessmentUpdate(tools=result.tools)
    )
    await set_assessment_result(
        db,
        assessment_id,
        grade=result.grade,
        criteria_snapshot=result.criteria_snapshot,
    )

    if result.criteria_snapshot.all_met():
        existing = await get_completion_for_assessment(db, assessment_id)
        if existing is None:
            await create_completion(
                db,
                CompletionCreate(
                    assessment_id=assessment_id,
                    repo_url=repo_url,
                    criteria_snapshot=result.criteria_snapshot,
                ),
            )

    _clear_in_memory_state(assessment_id)


async def _persist_failure(
    db: aiosqlite.Connection,
    assessment_id: str,
    *,
    kind: AssessmentErrorKind,
    message: str,
    failed_step: AssessmentFailedStep,
    details: str | None,
) -> None:
    """Single source of truth for "the row failed" updates.

    Used by the exception handler, the cancellation handler, and the
    watchdog loop. Idempotent — calling it twice is harmless because the
    fields are simple overwrites.
    """
    await update_assessment(
        db,
        assessment_id,
        AssessmentUpdate(
            status="failed",
            error_kind=kind,
            error_message=message,
            error_details=details,
            failed_step=failed_step,
        ),
    )


def _clear_in_memory_state(assessment_id: str) -> None:
    _ASSESSMENT_STEPS.pop(assessment_id, None)
    _ASSESSMENT_TOOLS.pop(assessment_id, None)


def schedule_assessment_run(
    app: FastAPI,
    db: aiosqlite.Connection,
    engine: AssessmentEngineProtocol,
    assessment_id: str,
    repo_url: str,
) -> asyncio.Task[None]:
    """Fire-and-track an assessment run. Tasks self-evict on completion."""
    tasks: set[asyncio.Task[None]] = (
        getattr(app.state, "assessment_tasks", None) or set()
    )
    task = asyncio.create_task(
        run_and_persist_assessment(db, engine, assessment_id, repo_url),
        name=f"assessment:{assessment_id}",
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    app.state.assessment_tasks = tasks
    return task
