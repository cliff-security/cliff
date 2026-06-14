"""Deep dive schema contracts (ADR-0052 §2) — additive over TriageOutput."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cliff.agents.schemas import (
    Challenge,
    ChallengeReviewer,
    DeepReachability,
    Disproof,
    ExploitHypothesis,
    ExploitPlan,
    FindingFacts,
    ReproRecipe,
    RuleOutResult,
    TriageOutput,
    TriageProvenance,
)


def test_triage_output_backward_compatible():
    """A pre-deep-dive verdict (the shipped shape) still loads; the new blocks
    default to None so the UI and persisted rows are unaffected."""
    out = TriageOutput.model_validate({"verdict": "real", "confidence": 0.9})
    assert out.exploit_plan is None
    assert out.challenge is None
    assert out.provenance is None
    # The ADR-0051 pairing invariant still holds.
    assert out.recommended_close is None


def test_triage_output_with_deep_dive_blocks():
    out = TriageOutput(
        verdict="real",
        confidence=0.88,
        exploit_plan=ExploitPlan(
            hypotheses=[
                ExploitHypothesis(
                    id="h1",
                    trigger_condition="unauth POST /import",
                    reached_sink="app/import.py:42",
                    impact_class="RCE",
                    repro_recipe=ReproRecipe(trigger=["curl ..."]),
                    confidence=0.7,
                )
            ],
            primary_hypothesis_id="h1",
        ),
        challenge=Challenge(
            verdict_holds=True,
            reviewers=[ChallengeReviewer(lens="reachability", verdict="holds")],
        ),
        provenance=TriageProvenance(steps_run=["gather_facts", "trace_path"], traced_sha="abc"),
    )
    # round-trips
    again = TriageOutput.model_validate(out.model_dump())
    assert again.exploit_plan.primary_hypothesis_id == "h1"
    assert again.provenance.traced_sha == "abc"
    assert again.challenge.verdict_holds is True


def test_exploit_plan_defaults_empty():
    plan = ExploitPlan()
    assert plan.hypotheses == []
    assert plan.no_credible_exploit is False


def test_rule_out_kill():
    r = RuleOutResult(
        killed=True,
        kill_class="root_cause_in_nonship_code",
        kill_evidence="tests/fixtures/x.py:3",
        recommended_verdict_on_kill="false_positive",
    )
    assert r.killed
    assert r.recommended_verdict_on_kill == "false_positive"


def test_rule_out_rejects_bad_kill_class():
    with pytest.raises(ValidationError):
        RuleOutResult(killed=True, kill_class="totally-made-up")


def test_deep_reachability_reached_enum():
    reach = DeepReachability(reached="no", disproof=Disproof(guard_location="auth.py:10"))
    assert reach.reached == "no"
    assert reach.disproof.guard_location == "auth.py:10"
    with pytest.raises(ValidationError):
        DeepReachability(reached="maybe")


def test_disproof_requires_guard_location():
    with pytest.raises(ValidationError):
        Disproof()


def test_finding_facts_defaults():
    facts = FindingFacts(vuln_class="ssti")
    assert facts.root_cause_candidates == []
    assert facts.static_evidence == []
