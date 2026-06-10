"""Unit tests for the escalation gate + budget (ADR-0052 §1)."""

from __future__ import annotations

from cliff.agents.triage_deep.escalation import decide_escalation, is_high_stakes

LOW = {"raw_severity": "low"}
CRIT = {"raw_severity": "critical"}
NET = {"raw_severity": "medium", "internet_facing": True}


def test_needs_review_always_escalates():
    d = decide_escalation("needs_review", LOW, budget_remaining=0)
    assert d.escalate is True


def test_clear_low_stakes_does_not_escalate():
    d = decide_escalation("unexploitable", LOW, budget_remaining=10)
    assert d.escalate is False


def test_high_stakes_escalates_with_budget():
    d = decide_escalation("real", CRIT, budget_remaining=3)
    assert d.escalate is True
    assert "high-stakes" in d.reason


def test_severity_alone_does_not_escalate_without_budget():
    # The load-bearing cost control: a flood of high-severity findings can't
    # all deep-dive once the per-assessment budget is spent.
    d = decide_escalation("real", CRIT, budget_remaining=0)
    assert d.escalate is False
    assert "budget" in d.reason


def test_reports_always_escalate():
    d = decide_escalation("real", LOW, budget_remaining=0, source="report")
    assert d.escalate is True


def test_internet_facing_is_high_stakes():
    assert is_high_stakes(NET) is True
    assert is_high_stakes(LOW) is False
