"""DeepDiveRunner orchestration — every fail-cheap exit + the final assembly.

Stages are injected fakes, so each path is exercised deterministically without a
model (ADR-0052 §2).
"""

from __future__ import annotations

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


def _disproof(result: Challenge):
    async def _f(deps, model):
        return result

    return _f


async def _run(stages, rk=RK, *, can_clear=True):
    runner = DeepDiveRunner(MODELS, stages=stages, can_clear=can_clear)
    return await runner.run(
        finding={"title": "x"}, repo_knowledge=rk, clone_dir="/tmp/x", traced_sha="sha1"
    )


async def test_corroborated_kill_exits_at_rule_out():
    # duplicate_of_known is corroborated by a prior issue in the threat history.
    rk = {"threat": {"prior_issues": [{"id": "GHSA-x"}]}}
    stages = DeepDiveStages(
        gather=_stage({"vuln_class": "rce"}),
        rule_out=_stage(
            {
                "killed": True,
                "kill_class": "duplicate_of_known",
                "dedup_match": "GHSA-x",  # names the specific prior issue
                "recommended_verdict_on_kill": "false_positive",
            }
        ),
    )
    out = await _run(stages, rk)
    assert out.verdict == "false_positive"
    assert out.provenance.exit_stage == "rule_out"
    assert out.provenance.steps_run == ["gather_facts", "rule_out"]


async def test_duplicate_kill_without_matching_id_falls_through():
    # A duplicate_of_known kill that doesn't name a prior issue present in the
    # threat history is NOT corroborated — it must fall through to trace, never
    # clear on "the repo has some history".
    rk = {"threat": {"prior_issues": [{"id": "GHSA-x"}]}}
    stages = DeepDiveStages(
        gather=_stage({"vuln_class": "rce"}),
        rule_out=_stage(
            {"killed": True, "kill_class": "duplicate_of_known", "dedup_match": "GHSA-unrelated"}
        ),
        trace=_stage({"reached": "unknown"}),
    )
    out = await _run(stages, rk)
    assert out.verdict == "needs_review"  # fell through, did not clear at rule_out
    assert "trace_path" in out.provenance.steps_run


async def test_nonship_kill_needs_all_candidates_nonship():
    # root_cause_in_nonship_code must hold for EVERY candidate; one ship-code
    # candidate alongside a test file must NOT clear at the cheap gate.
    rk = {"code_map": {"excluded_roots": ["tests/*"]}}
    stages = DeepDiveStages(
        gather=_stage(
            {"root_cause_candidates": [{"file": "tests/test_x.py"}, {"file": "app/views.py"}]}
        ),
        rule_out=_stage({"killed": True, "kill_class": "root_cause_in_nonship_code"}),
        trace=_stage({"reached": "unknown"}),
    )
    out = await _run(stages, rk)
    assert out.verdict == "needs_review"  # fell through (app/views.py is ship code)
    assert "trace_path" in out.provenance.steps_run


async def test_uncorroborated_kill_falls_through_to_trace():
    # A "looks safe" kill with no structural backing must NOT clear at the cheap
    # gate — it falls through to trace_path (the false-clear guarantee).
    stages = DeepDiveStages(
        gather=_stage({"vuln_class": "rce", "root_cause_candidates": [{"file": "app/views.py"}]}),
        rule_out=_stage({"killed": True, "kill_class": "downstream_filter"}),
        trace=_stage(
            {"reached": "yes", "path": [{"file": "app/views.py", "line": 2, "role": "sink"}]}
        ),
        plan=_stage({"hypotheses": [{"id": "h1", "trigger_condition": "x"}]}),
        challenge=_challenge(
            Challenge(
                verdict_holds=True, reviewers=[ChallengeReviewer(lens="exploit", verdict="holds")]
            )
        ),
    )
    out = await _run(stages)  # RK has empty code_map/threat → kill not corroborated
    assert out.verdict == "real"  # proceeded past the uncorroborated kill
    assert out.provenance.exit_stage == "challenge"
    assert "rule_out" in out.provenance.steps_run


async def test_disproof_upheld_is_unexploitable():
    # A disproof CLEARS the finding, so it is adversarially challenged first; an
    # upheld guard → unexploitable.
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage(
            {
                "reached": "no",
                "disproof": {"guard_location": "auth.py:10", "explanation": "checked"},
            }
        ),
        disproof_challenge=_disproof(
            Challenge(
                verdict_holds=True,
                reviewers=[ChallengeReviewer(lens="bypass", verdict="holds")],
            )
        ),
    )
    out = await _run(stages)
    assert out.verdict == "unexploitable"
    assert out.exploitability.exploitable == "no"
    assert out.provenance.exit_stage == "disproof_challenge"
    assert "disproof_challenge" in out.provenance.steps_run
    # The disproof is surfaced as a proof check.
    assert any(c.detail == "auth.py:10" for c in out.checks)


async def test_disproof_refuted_is_needs_review():
    # The guard did not survive the challenge (phantom / bypassable) — the finding
    # must route to a human, never silently false-clear a real vuln.
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage(
            {
                "reached": "no",
                "disproof": {"guard_location": "auth.py:10", "explanation": "phantom"},
            }
        ),
        disproof_challenge=_disproof(
            Challenge(
                verdict_holds=False,
                downgraded_verdict="needs_review",
                reviewers=[
                    ChallengeReviewer(lens="bypass", verdict="refuted", refutation="../ slips past")
                ],
            )
        ),
    )
    out = await _run(stages)
    assert out.verdict == "needs_review"
    assert out.provenance.exit_stage == "disproof_challenge"


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
        trace=_stage(
            {
                "reached": "yes",
                "path": [{"file": "a.py", "line": 3, "symbol": "sink", "role": "sink"}],
            }
        ),
        plan=_stage(
            {
                "hypotheses": [{"id": "h1", "trigger_condition": "POST"}],
                "primary_hypothesis_id": "h1",
            }
        ),
        challenge=_challenge(
            Challenge(
                verdict_holds=True,
                reviewers=[ChallengeReviewer(lens="reachability", verdict="holds")],
            )
        ),
    )
    out = await _run(stages)
    assert out.verdict == "real"
    assert out.exploit_plan.primary_hypothesis_id == "h1"
    assert out.challenge.verdict_holds is True
    assert out.reachability.path[0].detail == "a.py:3"
    assert out.provenance.steps_run == [
        "gather_facts",
        "rule_out",
        "trace_path",
        "plan_exploit",
        "challenge",
    ]
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


# ── safety net: a weak/thin-lineup judge tier may detect + flag, never clear ──


async def test_weak_tier_disproof_clear_downgraded_to_needs_review():
    # can_clear=False: a would-be `unexploitable` (disproof upheld) -> needs_review.
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage(
            {"reached": "no", "disproof": {"guard_location": "a.py:1", "explanation": "ok"}}
        ),
        disproof_challenge=_disproof(
            Challenge(
                verdict_holds=True,
                reviewers=[ChallengeReviewer(lens="bypass", verdict="holds")],
            )
        ),
    )
    out = await _run(stages, can_clear=False)
    assert out.verdict == "needs_review"
    assert any(c.eyebrow == "Tier gate" for c in out.checks)


async def test_weak_tier_rule_out_kill_downgraded_to_needs_review():
    # can_clear=False: even a corroborated false_positive kill -> needs_review.
    rk = {"threat": {"prior_issues": [{"id": "GHSA-x"}]}}
    stages = DeepDiveStages(
        gather=_stage({"vuln_class": "rce"}),
        rule_out=_stage(
            {
                "killed": True,
                "kill_class": "duplicate_of_known",
                "dedup_match": "GHSA-x",
                "recommended_verdict_on_kill": "false_positive",
            }
        ),
    )
    out = await _run(stages, rk, can_clear=False)
    assert out.verdict == "needs_review"
    # the gate must also clear the stale recommended_close, not leave 'false_positive'
    assert out.recommended_close is None


async def test_weak_tier_still_reports_real():
    # Detection is unaffected — a `real` verdict stays real on a weak tier.
    stages = DeepDiveStages(
        gather=_stage({}),
        rule_out=_stage({"killed": False}),
        trace=_stage({"reached": "yes", "path": [{"file": "a.py", "line": 1, "role": "sink"}]}),
        plan=_stage({"hypotheses": [{"id": "h1", "trigger_condition": "x"}]}),
        challenge=_challenge(
            Challenge(
                verdict_holds=True,
                reviewers=[ChallengeReviewer(lens="exploit", verdict="holds")],
            )
        ),
    )
    out = await _run(stages, can_clear=False)
    assert out.verdict == "real"
