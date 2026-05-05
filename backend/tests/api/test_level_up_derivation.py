"""Tests for the ``derive_level_up`` pure function (IMPL-0009 / B7).

This is the largest new piece of derivation logic in the redesign — every
gate the dashboard's Level-up panel renders is computed here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opensec.api.routes._level_up import derive_level_up
from opensec.models.assessment import CriteriaSnapshot
from opensec.models.finding import Finding, IssueDerived


def _finding(
    *,
    id: str,
    type: str,
    severity: str,
    section: str = "todo",
    stage: str = "todo",
    title: str = "",
) -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id=id,
        source_type="trivy" if type == "dependency" else "trivy-secret",
        source_id=f"src-{id}",
        title=title or f"Finding {id}",
        type=type,
        normalized_priority=severity,
        status="new",
        created_at=now,
        updated_at=now,
        derived=IssueDerived(section=section, stage=stage),
    )


def _posture_finding(
    *,
    name: str,
    passing: bool,
    grade_impact: str = "counts",
) -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id=f"posture-{name}",
        source_type="opensec-posture",
        source_id=name,
        title=name,
        type="posture",
        # Posture findings carry ``status='passed'`` when the latest scan reports
        # them passing; failing checks live as ``status='new'`` per ADR-0027.
        status="passed" if passing else "new",
        grade_impact=grade_impact,
        raw_payload={"check_name": name},
        created_at=now,
        updated_at=now,
        derived=IssueDerived(section="todo" if not passing else "done", stage="todo"),
    )


def _all_passing_criteria() -> CriteriaSnapshot:
    return CriteriaSnapshot(
        no_critical_vulns=True,
        no_high_vulns=True,
        security_md_present=True,
        dependabot_present=True,
        branch_protection_enabled=True,
        no_secrets_detected=True,
        actions_pinned_to_sha=True,
        no_stale_collaborators=True,
        code_owners_exists=True,
        secret_scanning_enabled=True,
        posture_checks_passing=15,
        posture_checks_total=15,
    )


# ─── grade A · already at top ───────────────────────────────────────────────


def test_grade_a_returns_hold_the_line_with_no_gates() -> None:
    out = derive_level_up(
        grade="A",
        criteria_snapshot=_all_passing_criteria(),
        open_findings=[],
        posture_findings=[],
    )
    assert out is not None
    assert out.current == "A"
    assert out.next is None
    assert out.gates == []
    assert "Hold the line" in out.summary or "hold" in out.summary.lower()


def test_no_grade_yet_returns_none() -> None:
    out = derive_level_up(
        grade=None,
        criteria_snapshot=None,
        open_findings=[],
        posture_findings=[],
    )
    assert out is None


# ─── grade B → A ────────────────────────────────────────────────────────────


def test_grade_b_to_a_with_one_open_critical_in_review_emits_ready_to_review() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_critical_vulns": False})
    crit = _finding(
        id="i-001",
        type="dependency",
        severity="critical",
        section="review",
        stage="plan_ready",
        title="RCE in lodash",
    )
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[crit],
        posture_findings=[],
    )
    assert out is not None
    assert out.current == "B" and out.next == "A"
    assert len(out.gates) == 1
    gate = out.gates[0]
    assert gate.id == "criticals_open"
    assert gate.label == "Close the open Critical"
    assert gate.current == 1 and gate.target == 0
    assert gate.unit == "critical"
    assert gate.status == "ready_to_review"
    assert gate.action_label == "Review plan"
    assert gate.action_href == "/issues?open=i-001"


def test_grade_b_to_a_with_pr_ready_secret_emits_pr_ready() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_secrets_detected": False})
    secret = _finding(
        id="i-004",
        type="secret",
        severity="high",
        section="review",
        stage="pr_ready",
    )
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[secret],
        posture_findings=[],
    )
    assert out is not None
    assert len(out.gates) == 1
    gate = out.gates[0]
    assert gate.id == "secrets_open"
    assert gate.status == "pr_ready"
    assert gate.action_label == "Open PR"
    assert gate.action_href == "/issues?open=i-004"


def test_grade_b_to_a_with_executor_running_emits_in_progress() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_critical_vulns": False})
    crit = _finding(
        id="i-006",
        type="dependency",
        severity="critical",
        section="in_progress",
        stage="generating",
    )
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[crit],
        posture_findings=[],
    )
    assert out is not None
    gate = out.gates[0]
    assert gate.status == "in_progress"
    assert gate.action_label == "Open Review"
    assert gate.action_href == "/issues?section=review"


def test_grade_b_to_a_high_findings_target_three() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_high_vulns": False})
    highs = [
        _finding(id=f"h-{i}", type="dependency", severity="high")
        for i in range(5)
    ]
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=highs,
        posture_findings=[],
    )
    assert out is not None
    gate = out.gates[0]
    assert gate.id == "highs_over_target"
    assert gate.label == "Bring High findings to ≤ 3"
    assert gate.current == 5 and gate.target == 3
    assert gate.unit == "high findings"


def test_singular_vs_plural_critical_label() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_critical_vulns": False})

    one_crit = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[_finding(id="i-x", type="dependency", severity="critical")],
        posture_findings=[],
    )
    assert one_crit is not None
    assert one_crit.gates[0].label == "Close the open Critical"

    two_crits = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[
            _finding(id="i-x", type="dependency", severity="critical"),
            _finding(id="i-y", type="dependency", severity="critical"),
        ],
        posture_findings=[],
    )
    assert two_crits is not None
    assert two_crits.gates[0].label == "Close the 2 open Criticals"


# ─── posture aggregate gate ─────────────────────────────────────────────────


def test_posture_aggregate_gate_marked_auto_fixable_when_security_md_unmet() -> None:
    snap = _all_passing_criteria().model_copy(
        update={"security_md_present": False, "posture_checks_passing": 14}
    )
    posture = [
        _posture_finding(name="security_md", passing=False),
    ]
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[],
        posture_findings=posture,
    )
    assert out is not None
    gate = out.gates[0]
    assert gate.id == "posture_remaining"
    assert gate.status == "auto_fixable"
    assert gate.auto_fixable_check_names == ["security_md"]
    assert gate.action_label.startswith("Auto-fix")


def test_posture_aggregate_gate_todo_when_only_non_fixable_unmet() -> None:
    snap = _all_passing_criteria().model_copy(
        update={
            "branch_protection_enabled": False,
            "no_stale_collaborators": False,
            "posture_checks_passing": 13,
        }
    )
    posture = [
        _posture_finding(name="branch_protection", passing=False),
        _posture_finding(name="stale_collaborators", passing=False),
    ]
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[],
        posture_findings=posture,
    )
    assert out is not None
    gate = out.gates[0]
    assert gate.status == "todo"
    assert gate.action_label == "Start"
    assert gate.auto_fixable_check_names == []


# ─── summary copy ──────────────────────────────────────────────────────────


def test_summary_counts_one_click_gates() -> None:
    snap = _all_passing_criteria().model_copy(
        update={
            "no_critical_vulns": False,
            "no_secrets_detected": False,
            "security_md_present": False,
            "posture_checks_passing": 14,
        }
    )
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[
            _finding(
                id="i-1",
                type="dependency",
                severity="critical",
                section="review",
                stage="plan_ready",
            ),
            _finding(
                id="i-2",
                type="secret",
                severity="high",
                section="review",
                stage="pr_ready",
            ),
        ],
        posture_findings=[_posture_finding(name="security_md", passing=False)],
    )
    assert out is not None
    # 3 gates: 1 ready_to_review + 1 pr_ready + 1 auto_fixable; 2 are one-click.
    assert ("Three things" in out.summary) or ("3 things" in out.summary)
    assert " A" in out.summary  # "between you and an A."
    # One-click count = pr_ready + auto_fixable = 2.
    assert ("Two are one-click" in out.summary) or ("2 are one-click" in out.summary)


# ─── cap at 4 gates ─────────────────────────────────────────────────────────


def test_gates_capped_at_four_dropping_most_expensive() -> None:
    snap = _all_passing_criteria().model_copy(
        update={
            "no_critical_vulns": False,
            "no_high_vulns": False,
            "no_secrets_detected": False,
            "security_md_present": False,
            "code_owners_exists": False,
            "posture_checks_passing": 13,
        }
    )
    open_findings = [
        _finding(
            id="i-c", type="dependency", severity="critical",
            section="review", stage="plan_ready",
        ),
        *[_finding(id=f"i-h{i}", type="dependency", severity="high") for i in range(5)],
        _finding(
            id="i-s", type="secret", severity="high",
            section="review", stage="pr_ready",
        ),
    ]
    posture = [
        _posture_finding(name="security_md", passing=False),
        _posture_finding(name="code_owners_exists", passing=False),
    ]
    out = derive_level_up(
        grade="F",
        criteria_snapshot=snap,
        open_findings=open_findings,
        posture_findings=posture,
    )
    assert out is not None
    assert len(out.gates) == 4


# ─── unknown criteria default to unmet (conservative) ──────────────────────


def test_unknown_critical_criterion_treated_as_unmet() -> None:
    snap = _all_passing_criteria().model_copy(update={"no_critical_vulns": None})
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[
            _finding(
                id="i-001",
                type="dependency",
                severity="critical",
                section="review",
                stage="plan_ready",
            )
        ],
        posture_findings=[],
    )
    assert out is not None
    assert len(out.gates) == 1
    assert out.gates[0].id == "criticals_open"


def test_criterion_unmet_but_no_findings_emits_no_gate() -> None:
    """Race-condition edge: criteria says fail, but bucket is empty.

    The snapshot is conservative, but a gate with current=0 and target=0
    is not actionable — drop it.
    """
    snap = _all_passing_criteria().model_copy(update={"no_critical_vulns": False})
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[],  # no critical findings
        posture_findings=[],
    )
    assert out is not None
    # No gate emitted — current == target == 0 is not a real bucket to act on.
    assert out.gates == []


def test_high_findings_under_target_emits_no_gate() -> None:
    """If high count is already ≤ 3, the gate is met — drop it."""
    snap = _all_passing_criteria().model_copy(update={"no_high_vulns": False})
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[
            _finding(id="h-1", type="dependency", severity="high"),
            _finding(id="h-2", type="dependency", severity="high"),
        ],
        posture_findings=[],
    )
    assert out is not None
    assert out.gates == []


# ─── grade transitions ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,expected_next",
    [("F", "D"), ("D", "C"), ("C", "B"), ("B", "A")],
)
def test_grade_transitions(current: str, expected_next: str) -> None:
    out = derive_level_up(
        grade=current,
        criteria_snapshot=CriteriaSnapshot(),  # everything False
        open_findings=[],
        posture_findings=[],
    )
    assert out is not None
    assert out.current == current
    assert out.next == expected_next
