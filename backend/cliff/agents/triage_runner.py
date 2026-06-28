"""Triage run path (ADR-0051 / IMPL-0024 V1-4).

Reuses the workspace agent-execution machinery rather than standing up a second
pipeline. For a **scanner** finding a triage run is enricher → exposure →
deterministic synthesis; for a **report** finding it is a single
``report_triager`` run (which carries its own dual-persist). Either way the
verdict lands in both the chat timeline and ``sidebar.triage`` (the CLAUDE.md
agent-output rule).

Triage never advances ``Finding.status``: a finding stays ``new`` through
triage and only becomes ``triaged`` on human confirmation of a ``real`` verdict
(the Plan gate — ADR-0051 §6).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cliff.agents.runtime.triage_synthesizer import synthesize_triage
from cliff.agents.schemas import TriageOutput
from cliff.agents.sidebar_mapper import map_and_upsert
from cliff.agents.triage_codemap import resolve_by_code_map
from cliff.agents.triage_deep.integration import maybe_deep_dive
from cliff.db.repo_agent_run import (
    create_agent_run,
    list_latest_runs_by_workspace_ids,
    update_agent_run,
)
from cliff.db.repo_finding import get_finding
from cliff.db.repo_sidebar import get_sidebar
from cliff.models import AgentRunCreate, AgentRunUpdate
from cliff.repos.dao import get_repo_by_url
from cliff.repos.service import default_repo_dir_manager

if TYPE_CHECKING:
    import aiosqlite

    from cliff.models import Finding, Workspace

logger = logging.getLogger(__name__)

#: ``source_type`` of an inbound vulnerability report (vs a scanner finding).
#: Set by the normalizer's report branch (ADR-0022/0023 extension, M3).
REPORT_SOURCE_TYPE = "report"

#: The pure-function "agent" key the synthesis output persists under. Not a
#: real agent run — the chat card + sidebar are written here directly.
SYNTHESIZER_AGENT_TYPE = "triage_synthesizer"

_VERDICT_LABEL = {
    "real": "Real risk",
    "unexploitable": "Not exploitable",
    "false_positive": "False positive",
    "needs_review": "Needs your review",
}


def _confidence_word(confidence: float) -> str:
    if confidence >= 0.85:
        return "High"
    if confidence >= 0.70:
        return "Medium"
    return "Low"


def _verdict_summary(triage: TriageOutput) -> str:
    """One-line human-readable verdict for the chat-timeline card."""
    pct = round(triage.confidence * 100)
    word = _confidence_word(triage.confidence)
    reason = ""
    if triage.exploitability and triage.exploitability.reason:
        reason = triage.exploitability.reason
    elif triage.reachability and triage.reachability.summary:
        reason = triage.reachability.summary
    label = _VERDICT_LABEL.get(triage.verdict, triage.verdict)
    line = f"**Triage verdict: {label}** ({word} · {pct}%)."
    return f"{line} {reason}".strip()


async def _persist_synthesis(
    db: aiosqlite.Connection, workspace_id: str, triage: TriageOutput
) -> None:
    """Dual-persist the synthesized verdict: a chat-timeline card (a completed
    ``triage_synthesizer`` agent_run) + ``sidebar.triage``."""
    dumped = triage.model_dump()
    run = await create_agent_run(
        db,
        workspace_id,
        AgentRunCreate(agent_type=SYNTHESIZER_AGENT_TYPE, status="running"),
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            status="completed",
            summary_markdown=_verdict_summary(triage),
            confidence=triage.confidence,
            structured_output=dumped,
        ),
    )
    await map_and_upsert(db, workspace_id, SYNTHESIZER_AGENT_TYPE, dumped)


def _structured_output(runs: dict[str, Any], agent_type: str) -> dict[str, Any] | None:
    run = runs.get(agent_type)
    return run.structured_output if run is not None else None


async def _load_code_map(db: aiosqlite.Connection, repo_url: str | None) -> dict[str, Any] | None:
    """The repo's cached code_map, or None when there's no ready profile — the
    same resolution the Deep dive uses (cliff/agents/triage_deep/integration.py).

    Returns None (falls through to Deep dive) on any read/parse failure, or
    when the artifact is not a dict — triage must never crash on a corrupt
    code_map.
    """
    if not repo_url:
        return None
    repo = await get_repo_by_url(db, repo_url)
    if repo is None or repo.profile_status != "ready":
        return None
    try:
        result = default_repo_dir_manager().read_artifact(repo.id, "code_map")
    except Exception:
        logger.debug(
            "code_map unreadable for repo %s — falling through to Deep dive", repo_url
        )
        return None
    if not isinstance(result, dict):
        return None
    return result


async def run_triage(
    executor: Any,
    db: aiosqlite.Connection,
    workspace: Workspace,
    *,
    env_vars: dict[str, str],
    ai_env: dict[str, str] | None = None,
    model_full_id: str | None = None,
) -> TriageOutput | None:
    """Run triage for *workspace*'s finding.

    Scanner triage always lands a verdict: a failed prerequisite degrades to
    ``needs_review`` rather than crashing (so the CLI never strands on a
    poll-timeout). The report path may still return ``None`` if the report
    triager produced no verdict.

    ``ai_env`` + ``model_full_id`` (the canonical AI state) enable the agentic
    Deep dive on escalation; without them triage stays the Quick read (ADR-0052).
    """
    finding = await get_finding(db, workspace.finding_id)
    if finding is None:
        raise ValueError(f"workspace {workspace.id} has no finding")

    if finding.source_type == REPORT_SOURCE_TYPE:
        return await _run_report_triage(
            executor,
            db,
            workspace,
            finding=finding,
            env_vars=env_vars,
            ai_env=ai_env,
            model_full_id=model_full_id,
        )
    return await _run_scanner_triage(
        executor,
        db,
        workspace,
        finding=finding,
        env_vars=env_vars,
        ai_env=ai_env,
        model_full_id=model_full_id,
    )


async def _run_scanner_triage(
    executor: Any,
    db: aiosqlite.Connection,
    workspace: Workspace,
    *,
    finding: Finding,
    env_vars: dict[str, str],
    ai_env: dict[str, str] | None = None,
    model_full_id: str | None = None,
) -> TriageOutput | None:
    prereq_failed = False
    failed_agent: str | None = None
    for agent_type in ("finding_enricher", "exposure_analyzer"):
        result = await executor.execute(
            workspace.id,
            agent_type,
            db,
            workspace_dir=workspace.workspace_dir,
            env_vars=env_vars,
        )
        status = getattr(result, "status", None)
        # Proceed ONLY on a completed prerequisite. Any other result status —
        # failed, rate_limited, awaiting_permission, or a future addition — is a
        # non-completion and must degrade, not be mistaken for success.
        if result is None or status != "completed":
            # A failed prerequisite (e.g. the exposure agent timing out on a
            # deploy-time SQL file) must NOT abort with no verdict — that strands
            # the CLI on a poll-timeout (exit 1) and leaves the UI without a
            # result. Degrade to a verdict synthesized from whatever DID run: a
            # failed run leaves no structured_output, so the synthesizer's
            # undetermined path yields needs_review. Triage always lands a
            # verdict; never a silent clear, never a crash.
            logger.warning(
                "Triage prerequisite %s ended status=%s for workspace %s — "
                "degrading to needs_review",
                agent_type, status, workspace.id,
            )
            prereq_failed = True
            failed_agent = agent_type
            break

    latest = await list_latest_runs_by_workspace_ids(db, [workspace.id])
    runs = latest.get(workspace.id, {})
    enrichment = _structured_output(runs, "finding_enricher")
    exposure = _structured_output(runs, "exposure_analyzer")

    if prereq_failed:
        # Don't synthesize from a PRIOR attempt's stale output: the failed agent
        # produced no fresh output this run, and an enricher failure breaks the
        # loop before exposure runs at all — so ``list_latest_runs`` could hand
        # back a confident exposure from an earlier triage and project a false
        # ``real``. Drop the failed agent's input (and everything downstream of
        # it) so the synthesizer lands on its missing-input needs_review.
        if failed_agent == "finding_enricher":
            enrichment = exposure = None
        else:  # exposure_analyzer
            exposure = None

    quick = synthesize_triage(enrichment, exposure, finding_type=finding.type)

    # Partial inputs from a failed prerequisite → land the degraded needs_review
    # and stop. Never escalate a partial quick read to the Deep dive (the same
    # provider trouble that just failed a prerequisite would likely stall it too).
    if prereq_failed:
        await _persist_synthesis(db, workspace.id, quick)
        return quick

    # Build the finding context once (path comes from the scanner raw_payload —
    # assessment/to_findings.py stores the flagged file under raw_payload["path"]).
    finding_ctx = {
        **finding.model_dump(mode="json"),
        "internet_facing": (exposure or {}).get("internet_facing"),
        "location": (finding.raw_payload or {}).get("path"),
    }

    # Deterministic code_map gate (SP2): clear non-ship findings before the LLM
    # Deep dive. A match is a structural fact (this code does not ship), gated on
    # the repo profile; a miss falls through unchanged.
    code_map = await _load_code_map(db, workspace.repo_url)
    cleared = resolve_by_code_map(finding_ctx, code_map)
    if cleared is not None:
        await _persist_synthesis(db, workspace.id, cleared)
        return cleared

    # Escalate to the agentic Deep dive when warranted (ADR-0052). Best-effort:
    # any failure keeps the cheap Quick-read verdict — triage never breaks.
    final = quick
    try:
        deep = await maybe_deep_dive(
            db,
            finding=finding_ctx,
            quick=quick,
            repo_url=workspace.repo_url,
            enrichment=enrichment,
            exposure=exposure,
            ai_env=ai_env,
            model_full_id=model_full_id,
        )
        if deep is not None:
            final = deep
    except Exception:
        logger.exception(
            "deep dive failed for workspace %s — keeping the quick verdict",
            workspace.id,
        )

    await _persist_synthesis(db, workspace.id, final)
    return final


async def _run_report_triage(
    executor: Any,
    db: aiosqlite.Connection,
    workspace: Workspace,
    *,
    finding: Finding,
    env_vars: dict[str, str],
    ai_env: dict[str, str] | None = None,
    model_full_id: str | None = None,
) -> TriageOutput | None:
    """Run the report triager (read-only repo access). It persists its own
    chat card + ``sidebar.triage`` via the executor's standard path; we read
    the verdict back to return it."""
    result = await executor.execute(
        workspace.id,
        "report_triager",
        db,
        workspace_dir=workspace.workspace_dir,
        env_vars=env_vars,
    )
    status = getattr(result, "status", None)
    if result is None or status != "completed":  # proceed only on completion
        logger.warning(
            "Report triage aborted: status=%s for workspace %s", status, workspace.id
        )
        return None

    sidebar = await get_sidebar(db, workspace.id)
    if sidebar is None or not sidebar.triage:
        return None
    quick = TriageOutput.model_validate(sidebar.triage)

    # Escalate to the agentic Deep dive when warranted (ADR-0052 — the report
    # variant starts at gather_facts). Best-effort: any failure keeps the report
    # triager's verdict — triage never breaks.
    final = quick
    try:
        deep = await maybe_deep_dive(
            db,
            finding={**finding.model_dump(mode="json")},
            quick=quick,
            repo_url=workspace.repo_url,
            enrichment=None,
            exposure=None,
            ai_env=ai_env,
            model_full_id=model_full_id,
            source="report",
        )
        if deep is not None:
            final = deep
            await _persist_synthesis(db, workspace.id, final)
    except Exception:
        logger.exception(
            "deep dive failed for report workspace %s — keeping the quick verdict",
            workspace.id,
        )
    return final


__all__ = ["REPORT_SOURCE_TYPE", "SYNTHESIZER_AGENT_TYPE", "run_triage"]
