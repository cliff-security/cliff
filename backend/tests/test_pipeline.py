"""Tests for the pipeline orchestrator."""

from __future__ import annotations

from cliff.agents.pipeline import (
    MAX_RETRY_ITERATIONS,
    PIPELINE_ORDER,
    VALID_AGENT_TYPES,
    suggest_next,
)

# Sections that come before exposure in the forward walk — tests targeting a
# later pipeline stage set these so suggest_next steps past them.
_PRE_EXPOSURE = {
    "enrichment": {"normalized_title": "Test"},
    "ownership": {"recommended_owner": "platform-team"},
}


def _base_snapshot(**overrides):
    """Build a context snapshot with all sections defaulting to None."""
    base = {
        "finding": {"id": "f-1"},
        "enrichment": None,
        "ownership": None,
        "exposure": None,
        "evidence": None,
        "plan": None,
        "remediation": None,
        "validation": None,
    }
    base.update(overrides)
    return base


class TestPipelineOrder:
    def test_pipeline_order_is_6_agent(self):
        assert PIPELINE_ORDER == [
            "finding_enricher",
            "owner_resolver",
            "exposure_analyzer",
            "evidence_collector",
            "remediation_planner",
            "remediation_executor",
        ]

    def test_owner_resolver_in_pipeline_order(self):
        """Q01-B09 — owner resolution is part of the forward walk so run-all
        populates sidebar.owner; it sits right after the enricher."""
        assert "owner_resolver" in PIPELINE_ORDER
        assert PIPELINE_ORDER.index("owner_resolver") == 1

    def test_validation_checker_not_in_pipeline_order(self):
        """Validation runs on-demand after remediation, never in the forward
        walk — it verifies a fix that does not exist yet."""
        assert "validation_checker" not in PIPELINE_ORDER

    def test_valid_agent_types_includes_all_agents(self):
        assert "finding_enricher" in VALID_AGENT_TYPES
        assert "owner_resolver" in VALID_AGENT_TYPES
        assert "exposure_analyzer" in VALID_AGENT_TYPES
        assert "remediation_planner" in VALID_AGENT_TYPES
        assert "remediation_executor" in VALID_AGENT_TYPES
        assert "validation_checker" in VALID_AGENT_TYPES


class TestSuggestNext:
    def test_empty_context_suggests_enricher(self):
        snapshot = _base_snapshot()
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "finding_enricher"
        assert result.priority == "recommended"
        assert result.action_type == "run_agent"

    def test_enrichment_done_suggests_owner_resolver(self):
        """Q01-B09 — after enrichment, the forward walk resolves ownership."""
        snapshot = _base_snapshot(enrichment={"normalized_title": "Test"})
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "owner_resolver"

    def test_ownership_done_suggests_exposure(self):
        snapshot = _base_snapshot(**_PRE_EXPOSURE)
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "exposure_analyzer"

    def test_enrichment_and_exposure_done_suggests_evidence(self):
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "evidence_collector"

    def test_evidence_done_suggests_planner(self):
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "remediation_planner"

    def test_plan_done_pauses_for_user_approval(self):
        """PRD-0006 Story 3 — after the planner runs, the pipeline pauses
        until the user explicitly approves. The run-all loop terminates on
        ``action_type='await_approval'``."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.action_type == "await_approval"
        assert result.agent_type is None

    def test_plan_approved_resumes_to_executor(self):
        """When the user approves (sidebar.plan.approved=True), the gate
        releases and the executor is suggested as normal."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"], "approved": True},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.agent_type == "remediation_executor"
        assert result.action_type == "run_agent"

    def test_plan_with_explicit_false_approval_still_pauses(self):
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"], "approved": False},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.action_type == "await_approval"

    def test_executor_pr_created_suggests_review_pr(self):
        """After executor creates PR, suggest review (not another agent)."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created", "pr_url": "https://github.com/..."},
        )
        result = suggest_next(snapshot)
        assert result is not None
        assert result.action_type == "review_pr"
        assert result.agent_type is None

    def test_executor_incomplete_stays_on_executor(self):
        """If remediation exists but status is not pr_created, don't suggest review."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "changes_made"},
        )
        result = suggest_next(snapshot)
        # Pipeline considers remediation present → should move to review_pr
        # only when status is pr_created. Otherwise pipeline is complete (None).
        assert result is None

    def test_validation_checker_not_suggested_by_default(self):
        """Even with validation missing, suggest_next does NOT suggest it."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created"},
        )
        result = suggest_next(snapshot)
        # Should suggest review_pr, never validation_checker
        assert result is not None
        assert result.agent_type != "validation_checker"

    def test_all_complete_pipeline_done(self):
        """Pipeline complete when remediation has pr_created + review_pr returned."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created"},
            validation={"verdict": "fixed", "recommendation": "close"},
        )
        result = suggest_next(snapshot)
        # review_pr is still suggested (it's the terminal action)
        assert result is not None
        assert result.action_type == "review_pr"

    def test_validation_not_fixed_retries_planner(self):
        """On-demand validation with not_fixed verdict re-suggests planner."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created"},
            validation={"verdict": "not_fixed", "recommendation": "replan"},
        )
        history = [
            {"agent_type": "remediation_planner", "status": "completed"},
        ]
        result = suggest_next(snapshot, history)
        assert result is not None
        assert result.agent_type == "remediation_planner"
        assert result.priority == "required"

    def test_validation_partially_fixed_retries(self):
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created"},
            validation={"verdict": "partially_fixed", "recommendation": "replan"},
        )
        result = suggest_next(snapshot, [])
        assert result is not None
        assert result.agent_type == "remediation_planner"

    def test_retry_limit_reached_returns_review_pr(self):
        """After max retries, fall back to review_pr (not None)."""
        snapshot = _base_snapshot(
            **_PRE_EXPOSURE,
            exposure={"recommended_urgency": "high"},
            evidence={"affected_files": [], "fix_safety": "safe_bump"},
            plan={"plan_steps": ["Step 1"]},
            remediation={"status": "pr_created"},
            validation={"verdict": "not_fixed", "recommendation": "replan"},
        )
        history = [
            {"agent_type": "remediation_planner", "status": "completed"}
            for _ in range(MAX_RETRY_ITERATIONS)
        ]
        result = suggest_next(snapshot, history)
        # Retry limit reached — fall back to review_pr
        assert result is not None
        assert result.action_type == "review_pr"
