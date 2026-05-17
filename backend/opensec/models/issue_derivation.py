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

from opensec.models import AgentRun, SidebarState, Workspace
from opensec.models.finding import Finding, IssueDerived


def _is_running(run: AgentRun | None) -> bool:
    return run is not None and run.status == "running"


def _is_failed(run: AgentRun | None) -> bool:
    # EF-B17 — ``rate_limited`` is a terminal non-success state; the UI
    # surfaces the same "retry" affordance for both, so the derivation
    # rules that key off "exec failed" also fire for "exec rate-limited".
    return run is not None and run.status in ("failed", "rate_limited")


def _has_plan(sidebar: SidebarState | None) -> bool:
    return sidebar is not None and bool(sidebar.plan)


def _pull_request(sidebar: SidebarState | None) -> dict:
    if sidebar is None or not sidebar.pull_request:
        return {}
    return sidebar.pull_request


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
        if _has_plan(sidebar):
            return out("review", "plan_ready")
        if _is_running(planner_run):
            return out("in_progress", "planning")
        # Status=in_progress with no agent activity yet (e.g. the user just
        # clicked Start and the planner hasn't reported back). Show as
        # in_progress / planning rather than falling back to todo so the
        # row visibly leaves the Todo section on click.
        return out("in_progress", "planning")

    return out("todo", "todo")
