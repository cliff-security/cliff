"""Unit tests for ``opensec.models.issue_derivation`` (IMPL-0006 T1).

Each row in IMPL-0006's derivation table has a corresponding case here, plus
the four edge cases the plan calls out. Phase 1 adapts the rules to the
``pull_request.status`` values the remediation_executor template actually
writes today (``pr_created`` / ``changes_made`` / ``failed`` /
``needs_approval``) — see ``Q1`` in the auto-execute plan.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opensec.models import AgentRun, Finding, SidebarState, Workspace
from opensec.models.issue_derivation import derive

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


def make_finding(
    *,
    status: str = "new",
    raw_payload: dict | None = None,
    exception_reason: str | None = None,
    exception_note: str | None = None,
) -> Finding:
    return Finding(
        id="f-1",
        source_type="trivy",
        source_id="vuln-001",
        title="CVE-2024-1234",
        status=status,  # type: ignore[arg-type]
        raw_payload=raw_payload,
        exception_reason=exception_reason,  # type: ignore[arg-type]
        exception_note=exception_note,
        created_at=NOW,
        updated_at=NOW,
    )


def make_workspace(workspace_id: str = "w-1") -> Workspace:
    return Workspace(
        id=workspace_id,
        finding_id="f-1",
        kind="finding_remediation",
        state="open",
        created_at=NOW,
        updated_at=NOW,
    )


def make_sidebar(
    *,
    workspace_id: str = "w-1",
    plan: dict | None = None,
    pull_request: dict | None = None,
) -> SidebarState:
    return SidebarState(
        workspace_id=workspace_id,
        plan=plan,
        pull_request=pull_request,
        updated_at=NOW,
    )


def make_run(agent_type: str, status: str = "running") -> AgentRun:
    return AgentRun(
        id=f"run-{agent_type}",
        workspace_id="w-1",
        agent_type=agent_type,
        status=status,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------------
# Cases 1-2 — Todo
# ----------------------------------------------------------------------------


def test_case_01_new_no_workspace_is_todo() -> None:
    result = derive(
        make_finding(status="new"),
        workspace=None,
        sidebar=None,
        latest_runs_by_type={},
    )

    assert result.section == "todo"
    assert result.stage == "todo"
    assert result.workspace_id is None
    assert result.pr_url is None


def test_case_02_triaged_with_workspace_no_plan_is_todo() -> None:
    workspace = make_workspace()
    result = derive(
        make_finding(status="triaged"),
        workspace=workspace,
        sidebar=make_sidebar(),
        latest_runs_by_type={},
    )

    assert result.section == "todo"
    assert result.stage == "todo"
    assert result.workspace_id == "w-1"


# ----------------------------------------------------------------------------
# Cases 3-10 — In progress + Review (the agent pipeline)
# ----------------------------------------------------------------------------


def test_case_03_planning() -> None:
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(),
        latest_runs_by_type={"remediation_planner": make_run("remediation_planner", "running")},
    )

    assert result.section == "in_progress"
    assert result.stage == "planning"


def test_case_04_plan_ready() -> None:
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(plan={"steps": [{"title": "Bump dep"}]}),
        latest_runs_by_type={
            "remediation_planner": make_run("remediation_planner", "completed"),
        },
    )

    assert result.section == "review"
    assert result.stage == "plan_ready"


def test_case_05_generating() -> None:
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(plan={"steps": [{"title": "Bump dep"}]}),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "running"),
        },
    )

    assert result.section == "in_progress"
    assert result.stage == "generating"


def test_case_06_pushing_branch_set_no_pr_url() -> None:
    """Adapted per Q1 — executor writes ``pr_created`` after the PR opens; the
    transient pre-PR state is signalled by ``branch_name`` being set with no
    ``pr_url``."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            plan={"steps": []},
            pull_request={"branch_name": "opensec/fix/cve-2024-1234", "pr_url": None},
        ),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "completed"),
        },
    )

    assert result.section == "in_progress"
    assert result.stage == "pushing"


def test_case_07_opening_pr_changes_made() -> None:
    """Adapted per Q1 — executor's ``changes_made`` status (no ``pr_url`` yet)
    maps to ``opening_pr``."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            plan={"steps": []},
            pull_request={
                "status": "changes_made",
                "branch_name": "opensec/fix/cve-2024-1234",
                "pr_url": None,
            },
        ),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "completed"),
        },
    )

    assert result.section == "in_progress"
    assert result.stage == "opening_pr"


def test_case_08_pr_ready() -> None:
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            plan={"steps": []},
            pull_request={
                "status": "pr_created",
                "pr_url": "https://github.com/o/r/pull/42",
                "branch_name": "opensec/fix/cve-2024-1234",
            },
        ),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "completed"),
        },
    )

    assert result.section == "review"
    assert result.stage == "pr_ready"
    assert result.pr_url == "https://github.com/o/r/pull/42"


def test_case_09_pr_awaiting_validation_after_merge() -> None:
    """Status flips to ``remediated`` upstream when the PR is merged; if the
    validator hasn't run yet, the issue is still on the user's plate (PR
    awaiting validation) — Review section."""
    result = derive(
        make_finding(status="remediated"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            pull_request={
                "status": "pr_created",
                "pr_url": "https://github.com/o/r/pull/42",
            },
        ),
        latest_runs_by_type={},
    )

    assert result.section == "review"
    assert result.stage == "pr_awaiting_val"
    assert result.pr_url == "https://github.com/o/r/pull/42"


def test_case_10_validating() -> None:
    result = derive(
        make_finding(status="remediated"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            pull_request={"status": "pr_created", "pr_url": "https://github.com/o/r/pull/42"},
        ),
        latest_runs_by_type={
            "validation_checker": make_run("validation_checker", "running"),
        },
    )

    assert result.section == "in_progress"
    assert result.stage == "validating"


# ----------------------------------------------------------------------------
# Cases 11-14 — Done (verdicts)
# ----------------------------------------------------------------------------


def test_case_11_validated_is_fixed() -> None:
    result = derive(
        make_finding(status="validated"),
        workspace=make_workspace(),
        sidebar=make_sidebar(),
        latest_runs_by_type={},
    )

    assert result.section == "done"
    assert result.stage == "fixed"


def test_case_12_closed_no_exception_is_fixed() -> None:
    result = derive(
        make_finding(status="closed"),
        workspace=make_workspace(),
        sidebar=make_sidebar(),
        latest_runs_by_type={},
    )

    assert result.section == "done"
    assert result.stage == "fixed"


def test_case_13_exception_false_positive() -> None:
    result = derive(
        make_finding(status="exception", raw_payload={"exception_reason": "false_positive"}),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )

    assert result.section == "done"
    assert result.stage == "false_positive"


def test_case_14_exception_default_accepted() -> None:
    """Exception without a reason defaults to ``accepted`` per the IMPL plan."""
    result = derive(
        make_finding(status="exception"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )

    assert result.section == "done"
    assert result.stage == "accepted"


# ----------------------------------------------------------------------------
# Phase 2 (IMPL-0007 §B2) — exception_reason column drives the verdict
# ----------------------------------------------------------------------------


def test_case_14a_exception_reason_false_positive() -> None:
    result = derive(
        make_finding(status="exception", exception_reason="false_positive"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert result.section == "done"
    assert result.stage == "false_positive"


def test_case_14b_exception_reason_wont_fix() -> None:
    result = derive(
        make_finding(status="exception", exception_reason="wont_fix"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert result.section == "done"
    assert result.stage == "wont_fix"


def test_case_14c_exception_reason_accepted_risk_maps_to_accepted() -> None:
    result = derive(
        make_finding(status="exception", exception_reason="accepted_risk"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert result.section == "done"
    assert result.stage == "accepted"


def test_case_14d_exception_reason_deferred() -> None:
    result = derive(
        make_finding(status="exception", exception_reason="deferred"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert result.section == "done"
    assert result.stage == "deferred"


def test_case_14e_legacy_raw_payload_reason_still_works() -> None:
    """Pre-Phase-2 rows (with ``raw_payload.exception_reason`` but no column)
    keep their derived stage so old findings don't regress to ``accepted``."""
    result = derive(
        make_finding(
            status="exception",
            raw_payload={"exception_reason": "false_positive"},
        ),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert result.section == "done"
    assert result.stage == "false_positive"


# ----------------------------------------------------------------------------
# Cases 15-18 — Conflict resolution + edge cases
# ----------------------------------------------------------------------------


def test_case_15_executor_running_beats_plan_ready() -> None:
    """Conflict: executor running AND plan present → ``generating``, not
    ``plan_ready``. PR/executor signals dominate plan-existence."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(plan={"steps": [{"title": "Bump dep"}]}),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "running"),
        },
    )

    assert result.stage == "generating"


def test_case_16_missing_sidebar_dispatches_on_finding_status() -> None:
    """When sidebar is None we dispatch on Finding.status:

    - ``new`` / ``triaged`` → todo (the user hasn't started yet)
    - ``in_progress`` → in_progress / planning (the user clicked Start; the
      planner just hasn't reported back yet — the row must visibly leave
      Todo so the click feels responsive, per PRD-0006 Story 2)
    - ``remediated`` → todo (defensive — without a sidebar there's no PR to
      review and no validator state to surface)
    """
    for status in ("new", "triaged"):
        result = derive(
            make_finding(status=status),
            workspace=make_workspace(),
            sidebar=None,
            latest_runs_by_type={},
        )
        assert result.section == "todo", f"status={status} should be todo"
        assert result.stage == "todo"

    in_progress = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=None,
        latest_runs_by_type={},
    )
    assert in_progress.section == "in_progress"
    assert in_progress.stage == "planning"


def test_case_17_failed_executor_surfaces_failed_stage() -> None:
    """A failed remediation_executor surfaces ``stage='failed'`` so the user
    sees an explicit error state (with Retry CTA) instead of being looped
    back to ``plan_ready`` — clicking Approve there would just re-fire the
    same failure."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(plan={"steps": [{"title": "Bump dep"}]}),
        latest_runs_by_type={
            "remediation_planner": make_run("remediation_planner", "completed"),
            "remediation_executor": make_run("remediation_executor", "failed"),
        },
    )

    assert result.section == "review"
    assert result.stage == "failed"


def test_failed_pr_push_surfaces_failed_stage() -> None:
    """A completed executor whose PR push 403'd records
    ``pull_request.status='failed'`` with a ``branch_name`` set. That must
    surface as ``failed``, not ``pushing`` (which would spin forever)."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            plan={"steps": [{"title": "Bump dep"}]},
            pull_request={
                "status": "failed",
                "branch_name": "opensec/fix/cve-2024-1234",
                "pr_url": None,
                "error_details": "403 — GH_TOKEN lacks push access",
            },
        ),
        latest_runs_by_type={
            "remediation_executor": make_run("remediation_executor", "completed"),
        },
    )

    assert result.section == "review"
    assert result.stage == "failed"


def test_case_18_conflict_pr_open_beats_planner_rerun() -> None:
    """Edge: an open PR plus a planner re-run in flight — PR existence wins
    (it's the user-visible signal that drives the action). Mirrors the
    derivation rules' "first match wins" ordering."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(
            plan={"steps": []},
            pull_request={
                "status": "pr_created",
                "pr_url": "https://github.com/o/r/pull/99",
            },
        ),
        latest_runs_by_type={
            "remediation_planner": make_run("remediation_planner", "running"),
        },
    )

    assert result.section == "review"
    assert result.stage == "pr_ready"


# ----------------------------------------------------------------------------
# Bonus coverage — ``workspace_id`` propagation + empty plan handling
# ----------------------------------------------------------------------------


def test_workspace_id_propagated_when_workspace_exists() -> None:
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace("w-abc"),
        sidebar=make_sidebar(plan={"steps": [{"title": "x"}]}),
        latest_runs_by_type={},
    )
    assert result.workspace_id == "w-abc"


def test_empty_plan_dict_is_not_plan_ready() -> None:
    """``plan = {}`` (empty dict) is not a real plan; it must not move the
    issue to Review."""
    result = derive(
        make_finding(status="in_progress"),
        workspace=make_workspace(),
        sidebar=make_sidebar(plan={}),
        latest_runs_by_type={},
    )
    assert result.section != "review"
    assert result.stage != "plan_ready"
