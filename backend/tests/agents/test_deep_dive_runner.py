"""DeepDiveRunner orchestration — every fail-cheap exit + the final assembly.

Stages are injected fakes, so each path is exercised deterministically without a
model (ADR-0052 §2).
"""

from __future__ import annotations

import pytest

from cliff.agents.schemas import Challenge, ChallengeReviewer
from cliff.agents.triage_deep.runner import DeepDiveRunner, DeepDiveStages

MODELS = {"cheap": None, "strong": None, "judge": None}
RK = {"profile": {"kind": "service"}, "code_map": {}, "threat": {}}


def _stage(value):
    async def _f(deps, model):
        return value

    return _f


def _challenge(result: Challenge):
    async def _f(deps, model, current_verdict):
        return result

    return _f


async def _run(stages):
    runner = DeepDiveRunner(MODELS, stages=stages)
    return await runner.run(
        finding={"title": "x"}, repo_knowledge=RK, clone_dir="/tmp/x", traced_sha="sha1"
    )


async def test_exit_at_rule_out_kill():
    stages = DeepDiveStages(
        gather=_stage({"vuln_class": "rce"}),
        rule_out=_stage(
            {"killed": True, "kill_class": "root_cause_in_nonship_code",
             "recommended_verdict_on_kill": "false_positive", "kill_evidence": "tests/x.py:1"}
        ),
    )
    out = await _run(stages)
    assert out.verdict == "false_positive"
    assert out.provenance.exit_stage == "rule_out"
    assert out.provenance.steps_run == ["gather_facts", "rule_out"]


async def test_exit_at_trace_disproof():
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "no", "disproof": {"guard_location": "auth.py:10", "explanation": "checked"}}),
    )
    out = await _run(stages)
    assert out.verdict == "unexploitable"
    assert out.exploitability.exploitable == "no"
    assert out.provenance.exit_stage == "trace_path"
    # The disproof is surfaced as a proof check.
    assert any(c.detail == "auth.py:10" for c in out.checks)


async def test_unknown_reachability_needs_review():
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "unknown"}),
    )
    out = await _run(stages)
    assert out.verdict == "needs_review"
    assert out.confidence < 0.7


async def test_reachable_no_exploit_is_hardening_unexploitable():
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "yes", "path": [{"file": "a.py", "line": 3, "role": "sink"}]}),
        plan=_stage({"no_credible_exploit": True}),
    )
    out = await _run(stages)
    # Reachable but no exploit → unexploitable (hardening), NOT needs_review.
    assert out.verdict == "unexploitable"
    assert out.provenance.exit_stage == "plan_exploit"
    assert "hardening" in out.exploitability.reason.lower()


async def test_full_real_verdict_when_challenge_holds():
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "yes", "path": [{"file": "a.py", "line": 3, "symbol": "sink", "role": "sink"}]}),
        plan=_stage({"hypotheses": [{"id": "h1", "trigger_condition": "POST"}], "primary_hypothesis_id": "h1"}),
        challenge=_challenge(
            Challenge(verdict_holds=True, reviewers=[ChallengeReviewer(lens="reachability", verdict="holds")])
        ),
    )
    out = await _run(stages)
    assert out.verdict == "real"
    assert out.exploit_plan.primary_hypothesis_id == "h1"
    assert out.challenge.verdict_holds is True
    assert out.reachability.path[0].detail == "a.py:3"
    assert out.provenance.steps_run == ["gather_facts", "rule_out", "trace_path", "plan_exploit", "challenge"]
    assert out.provenance.model_tiers["challenge"] == "judge"


async def test_challenge_downgrade_lowers_verdict():
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "yes", "path": []}),
        plan=_stage({"hypotheses": [], "no_credible_exploit": False}),
        challenge=_challenge(
            Challenge(
                verdict_holds=False,
                downgraded_verdict="needs_review",
                reviewers=[ChallengeReviewer(lens="exploit", verdict="refuted")],
                confidence_adjustment=-0.25,
            )
        ),
    )
    out = await _run(stages)
    assert out.verdict == "needs_review"
    assert out.challenge.verdict_holds is False
