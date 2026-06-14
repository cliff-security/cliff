"""Deep dive eval harness — the deterministic gates (ADR-0052 §Evaluation).

Keyless / CI lane: the graders are unit-tested directly, and ``run_deep_dive_eval``
is driven by a stub pipeline so the HARD gates (false-clear, citation grounding)
are proven to FIRE without a real model. The real golden datasets + the live
lane live in the private cliff-os/eval project.
"""

from __future__ import annotations

from cliff.agents.schemas import (
    ExploitHypothesis,
    ExploitPlan,
    TriageOutput,
    TriageReachability,
    TriageReachabilityNode,
)
from cliff.evals.cases import EvalCase
from cliff.evals.deep_dive_evaluators import (
    check_citation_grounding,
    check_false_clear,
    check_tool_boundary,
    check_verdict_match,
)
from cliff.evals.runners import run_deep_dive_eval

# ── graders ─────────────────────────────────────────────────────────────────


def test_false_clear_fires_on_cleared_real():
    assert check_false_clear("unexploitable", "real")[0] is False
    assert check_false_clear("false_positive", "real")[0] is False
    # Not a false-clear:
    assert check_false_clear("real", "real")[0] is True
    assert check_false_clear("unexploitable", "unexploitable")[0] is True
    assert check_false_clear("needs_review", "real")[0] is True  # not a clear


def test_citation_grounding(tmp_path):
    (tmp_path / "app.py").write_text("line1\nline2\nline3\n")
    good = {
        "exploit_plan": {"hypotheses": [{"reached_sink": "app.py:2"}]},
        "reachability": {"path": [{"detail": "app.py:1"}]},
    }
    assert check_citation_grounding(good, tmp_path)[0] is True

    missing = {"exploit_plan": {"hypotheses": [{"reached_sink": "ghost.py:1"}]}}
    assert check_citation_grounding(missing, tmp_path)[0] is False

    past_end = {"reachability": {"path": [{"detail": "app.py:999"}]}}
    assert check_citation_grounding(past_end, tmp_path)[0] is False


def test_citation_grounding_skips_prose(tmp_path):
    prose = {"reachability": {"path": [{"detail": "the request handler"}]}}
    # Not a parseable file:line → not a fabrication, skipped.
    assert check_citation_grounding(prose, tmp_path)[0] is True


def test_citation_grounding_catches_fabricated_disproof_guard(tmp_path):
    # A CLEAR verdict's load-bearing citation (the disproof guard / rule_out
    # evidence) lands in checks[].detail as a bare file:line with no '/'. The gate
    # must still ground it — a fabricated guard at a nonexistent file fails.
    (tmp_path / "app.py").write_text("line1\nline2\n")
    upheld = {"verdict": "unexploitable", "checks": [{"eyebrow": "Disproof", "detail": "app.py:1"}]}
    assert check_citation_grounding(upheld, tmp_path)[0] is True
    fabricated = {
        "verdict": "unexploitable",
        "checks": [{"eyebrow": "Disproof", "detail": "ghost.py:99"}],
    }
    assert check_citation_grounding(fabricated, tmp_path)[0] is False
    # line 0 doesn't resolve either
    assert check_citation_grounding(
        {"checks": [{"detail": "app.py:0"}]}, tmp_path
    )[0] is False


def test_tool_boundary_is_read_only():
    ok, reason = check_tool_boundary()
    assert ok is True
    assert "read" in reason and "grep" in reason


def test_verdict_match():
    assert check_verdict_match("real", "real")[0] is True
    assert check_verdict_match("real", "unexploitable")[0] is False
    assert check_verdict_match("real", None)[0] is True  # no expectation


# ── the runner + its gates end to end (stub pipeline) ───────────────────────


def _case(cid, verdict, files):
    return EvalCase.model_validate(
        {
            "id": cid,
            "tier": "ci",
            "finding": {"t": cid},
            "files": files,
            "expected": {"verdict": verdict},
        }
    )


def _stub(outputs):
    async def _run(case, repo_dir):
        return outputs[case.id]

    return _run


async def test_clean_case_passes():
    cases = [_case("ok", "real", {"app.py": "a\nb\nc\n"})]
    out = TriageOutput(
        verdict="real",
        confidence=0.85,
        reachability=TriageReachability(
            reached=True, path=[TriageReachabilityNode(label="sink", detail="app.py:2")]
        ),
        exploit_plan=ExploitPlan(
            hypotheses=[ExploitHypothesis(id="h1", trigger_condition="x", reached_sink="app.py:2")]
        ),
    )
    result = await run_deep_dive_eval(cases, run_pipeline=_stub({"ok": out}))
    assert result.passed is True
    assert result.hard_failures == []
    assert result.graded_rates["verdict_match"] == 1.0


async def test_false_clear_is_a_hard_failure():
    cases = [_case("bad", "real", {"app.py": "a\n"})]
    out = TriageOutput(verdict="unexploitable", confidence=0.8)
    result = await run_deep_dive_eval(cases, run_pipeline=_stub({"bad": out}))
    assert result.passed is False
    assert any("FALSE-CLEAR" in hf for hf in result.hard_failures)


async def test_fabricated_citation_is_a_hard_failure():
    cases = [_case("fab", "real", {"app.py": "a\n"})]
    out = TriageOutput(
        verdict="real",
        confidence=0.85,
        exploit_plan=ExploitPlan(
            hypotheses=[
                ExploitHypothesis(id="h1", trigger_condition="x", reached_sink="ghost.py:9")
            ]
        ),
    )
    result = await run_deep_dive_eval(cases, run_pipeline=_stub({"fab": out}))
    assert result.passed is False
    assert any("fabricated citation" in hf for hf in result.hard_failures)
