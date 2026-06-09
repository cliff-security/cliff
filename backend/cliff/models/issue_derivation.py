"""Issue derivation logic (IMPL-0006 T1).

Pure function that maps a Finding plus its workspace state, sidebar, and
latest agent runs into the four-section / 13-stage UI model documented
inline in IMPL-0006. No DB access — the caller batch-loads everything.

The rules table lives in IMPL-0006 §"Derivation contract". Phase 1 adapts
two rules to the ``pull_request.status`` values the remediation_executor
template actually writes today (``pr_created`` / ``changes_made`` /
``failed`` / ``needs_approval``); see Q1 in the auto-execute plan.
"""

from __future__ import annotations

from collections.abc import Mapping

from cliff.models import AgentRun, SidebarState, Workspace
from cliff.models.finding import Finding, IssueDerived


def _is_running(run: AgentRun | None) -> bool:
    return run is not None and run.status == "running"


def _is_failed(run: AgentRun | None) -> bool:
    # EF-B17 — ``rate_limited`` is a terminal non-success state; the UI
    # surfaces the same "retry" affordance for both, so the derivation
    # rules that key off "exec failed" also fire for "exec rate-limited".
    return run is not None and run.status in ("failed", "rate_limited")


def _permission_pending(run: AgentRun | None) -> bool:
    """True when the run is parked on an ``ask``-tier tool-use approval.

    Set by ``executor._handle_permission`` and cleared when the asyncio
    event resolves; also force-cleared by ``reconcile_orphaned_agent_runs``
    on backend startup so a crashed-mid-wait row can't surface a stale
    ``awaiting_permission`` after restart.
    """
    return run is not None and run.permission_pending


def _has_plan(sidebar: SidebarState | None) -> bool:
    return sidebar is not None and bool(sidebar.plan)


# Forward-pipeline agents that must succeed before the planner can run.
# ``remediation_planner`` and ``remediation_executor`` have their own
# dedicated derivation rules above (with PR-state / plan-state nuance), so
# they're intentionally excluded here.
_PREREQUISITE_AGENT_TYPES: tuple[str, ...] = (
    "finding_enricher",
    "owner_resolver",
    "exposure_analyzer",
    "evidence_collector",
)


def _any_prerequisite_failed(
    latest_runs_by_type: Mapping[str, AgentRun],
) -> bool:
    """True when any pre-plan pipeline agent's latest run failed.

    Mirrors ``_is_failed`` semantics (``failed`` or ``rate_limited``) so the
    same Retry CTA serves both shapes of LLM-side termination.
    """
    return any(
        _is_failed(latest_runs_by_type.get(agent_type))
        for agent_type in _PREREQUISITE_AGENT_TYPES
    )


def _pull_request(sidebar: SidebarState | None) -> dict:
    if sidebar is None or not sidebar.pull_request:
        return {}
    return sidebar.pull_request


# ADR-0051 / PRD-0008 — agents that produce a triage verdict. A run of any of
# these while the finding is still ``new`` is a triage run: the remediation
# flow only runs them after Start (status is already ``in_progress`` by then),
# so on a ``new`` finding they unambiguously mean "triage is in flight."
_TRIAGE_AGENT_TYPES: tuple[str, ...] = (
    "finding_enricher",
    "exposure_analyzer",
    "report_triager",
)


def _triage_running(latest_runs_by_type: Mapping[str, AgentRun]) -> bool:
    return any(_is_running(latest_runs_by_type.get(t)) for t in _TRIAGE_AGENT_TYPES)


def _triage_failed(latest_runs_by_type: Mapping[str, AgentRun]) -> bool:
    return any(_is_failed(latest_runs_by_type.get(t)) for t in _TRIAGE_AGENT_TYPES)


def _has_triage_verdict(sidebar: SidebarState | None) -> bool:
    return (
        sidebar is not None
        and isinstance(sidebar.triage, dict)
        and bool(sidebar.triage.get("verdict"))
    )


def derive(
    finding: Finding,
    *,
    workspace: Workspace | None,
    sidebar: SidebarState | None,
    latest_runs_by_type: Mapping[str, AgentRun],
) -> IssueDerived:
    """Compose the (section, stage, workspace_id, pr_url) tuple for a finding.

    ``latest_runs_by_type`` is keyed by ``AgentRun.agent_type`` and holds the
    most recent run for that type on this workspace (or absent if there isn't
    one). First-match-wins ordering — see the IMPL-0006 derivation table.
    """

    workspace_id = workspace.id if workspace else None
    pr_block = _pull_request(sidebar)
    pr_url = pr_block.get("pr_url") or None

    def out(section: str, stage: str) -> IssueDerived:
        return IssueDerived(
            section=section,  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            workspace_id=workspace_id,
            pr_url=pr_url,
        )

    # ---------- Done verdicts (terminal) ------------------------------------
    if finding.status == "exception":
        # PRD-0006 Phase 2 — the dedicated column wins. ``raw_payload`` is
        # consulted only as a legacy fallback so findings written before
        # migration 012 don't regress to the ``accepted`` default.
        reason = finding.exception_reason or (finding.raw_payload or {}).get(
            "exception_reason"
        )
        stage_by_reason = {
            "false_positive": "false_positive",
            # ADR-0051 §7 — distinct Done chip from false_positive.
            "unexploitable": "unexploitable",
            "wont_fix": "wont_fix",
            "accepted_risk": "accepted",
            "deferred": "deferred",
        }
        return out("done", stage_by_reason.get(reason, "accepted"))

    if finding.status in ("validated", "closed"):
        return out("done", "fixed")

    planner_run = latest_runs_by_type.get("remediation_planner")
    executor_run = latest_runs_by_type.get("remediation_executor")
    validator_run = latest_runs_by_type.get("validation_checker")

    if finding.status == "remediated" and _is_running(validator_run):
        return out("in_progress", "validating")

    if finding.status == "remediated" and validator_run is None and pr_url:
        return out("review", "pr_awaiting_val")

    if finding.status == "in_progress":
        # PR existence dominates planner re-runs (edge case 18 in IMPL plan).
        if pr_url:
            return out("review", "pr_ready")
        # Agent-permission approval gate — a running executor parked on an
        # ``ask``-tier tool-use request must surface in Review under the
        # new ``awaiting_permission`` stage, not the in-flight ``generating``
        # bucket. Placed before the ``running → generating`` branch by
        # design.
        if _is_running(executor_run) and _permission_pending(executor_run):
            return out("review", "awaiting_permission")
        if _is_running(executor_run):
            return out("in_progress", "generating")
        # Failed PR push — the executor recorded its work in sidebar
        # ``pull_request`` with ``status='failed'`` (e.g. ``GH_TOKEN lacks
        # push access`` → 403). Must precede the ``branch_name → pushing``
        # check below, because the branch name is set on failed pushes too
        # and would otherwise spin the row on "Pushing branch…" forever.
        if pr_block.get("status") == "failed":
            return out("review", "failed")
        if pr_block.get("status") == "changes_made":
            return out("in_progress", "opening_pr")
        if pr_block.get("branch_name"):
            return out("in_progress", "pushing")
        # Other error paths — failed executor run with no PR push attempted,
        # or planner failure before producing a plan. Surface ``failed``
        # explicitly so the UI can render the Retry CTA + error reason
        # instead of the misleading ``plan_ready`` fallback (which loops:
        # the user clicks Approve, the executor re-fails immediately).
        if _is_failed(executor_run) or (
            _is_failed(planner_run) and not _has_plan(sidebar)
        ):
            return out("review", "failed")
        # Pipeline-prerequisite agent failed (enricher / owner / exposure /
        # evidence). Without this rule, a failed enricher (e.g. OpenRouter
        # out-of-credits — the run completes with ``status='failed'`` and a
        # humanized error in ``summary_markdown``) leaves the issue silently
        # pinned at ``in_progress / planning`` because the default
        # fall-through below assumes "no agent activity yet." Surfacing it
        # as ``failed`` lets the side panel render the actual error message
        # plus a Retry CTA so the user can fix the upstream issue
        # (top up credits, swap provider, …) and resume.
        if not _has_plan(sidebar) and _any_prerequisite_failed(latest_runs_by_type):
            return out("review", "failed")
        # A running planner wins over an existing plan so a Refine re-run
        # surfaces ``planning`` (the side panel renders the "Reviewing the
        # advisory…" drafting widget). Without this ordering the prior
        # plan keeps the stage pinned at ``plan_ready`` and the user gets
        # no visible feedback that the agent is working.
        if _is_running(planner_run):
            return out("in_progress", "planning")
        if _has_plan(sidebar):
            return out("review", "plan_ready")
        # Status=in_progress with no agent activity yet (e.g. the user just
        # clicked Start and the planner hasn't reported back). Show as
        # in_progress / planning rather than falling back to todo so the
        # row visibly leaves the Todo section on click.
        return out("in_progress", "planning")

    # ---------- Triage (untriaged finding, ADR-0051 / PRD-0008) -------------
    # Triage runs on a ``new`` finding WITHOUT advancing its status — status
    # only moves to ``triaged`` on human confirmation of a ``real`` verdict
    # (ADR-0051 §6, which removed the enricher's new→triaged auto-advance). So
    # an untriaged finding routes here, never into the remediation flow above:
    # Plan is unreachable without a recorded ``real`` verdict (PRD-0008 Story 4).
    if finding.status == "new":
        # Triage reasoning in flight wins over everything else — a re-triage
        # after an earlier failure (one type's latest run failed while another
        # is now running) must show `triaging`, not the stale failure. Mirrors
        # the running-planner-beats-existing-plan rule above.
        if _triage_running(latest_runs_by_type):
            return out("in_progress", "triaging")
        # A failed triage run with no verdict yet → Retry affordance in Review
        # (never a silent stick in Todo).
        if _triage_failed(latest_runs_by_type) and not _has_triage_verdict(sidebar):
            return out("review", "failed")
        # Verdict produced, awaiting the human gate (real → accept,
        # needs_review → decide, unexploitable/false_positive → confirm close).
        # Lands in the existing "Needs you" section.
        if _has_triage_verdict(sidebar):
            return out("review", "triage_verdict")
        # Untriaged + idle → Todo with a Run-triage action.
        return out("todo", "todo")

    # ``triaged`` (verdict confirmed real, remediation not yet started) and any
    # other unhandled status fall through to Todo — the user opens the
    # workspace to remediate from here.
    return out("todo", "todo")
