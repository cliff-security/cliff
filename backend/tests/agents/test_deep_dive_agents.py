"""Deep dive agents — read-only boundary, shape, deterministic challenge.

Keyless: TestModel drives the agents (no real LLM); quality is the key-gated
eval. These assert the trust boundary, that each stage returns its validated
artifact, and the deterministic challenge resolution.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

import cliff.agents.triage_deep.agents as dd_agents
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools import bash, edit, gh, grep, read, webfetch
from cliff.agents.schemas import (
    Challenge,
    ChallengeReviewer,
    DeepReachability,
    ExploitPlan,
    FindingFacts,
    RuleOutResult,
)
from cliff.agents.triage_deep.agents import (
    DEEP_DIVE_TOKEN_LIMIT_CHEAP,
    DEEP_DIVE_TOKEN_LIMIT_STRONG,
    DEEP_DIVE_TOOLS,
    run_gather_facts,
    run_plan_exploit,
    run_rule_out,
    run_trace_path,
)
from cliff.agents.triage_deep.challenge import (
    CHALLENGE_LENSES,
    DISPROOF_LENSES,
    resolve_challenge,
    resolve_disproof,
    run_challenge_panel,
    run_disproof_challenge,
)


def test_deep_dive_is_read_only():
    assert (read, grep) == DEEP_DIVE_TOOLS
    for forbidden in (bash, edit, gh, webfetch):
        assert forbidden not in DEEP_DIVE_TOOLS


@pytest.fixture
def deps(tmp_path):
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "app.py").write_text("def handler(req):\n    eval(req.body)\n")
    return WorkspaceDeps(
        workspace_id="dd",
        workspace_dir=str(clone),
        finding={"source_type": "code", "title": "eval on request body"},
        prior_context={"profile": {"kind": "service"}, "code_map": {"ships_roots": ["**"]}},
    )


async def test_gather_facts_returns_findingfacts(deps):
    out = await run_gather_facts(deps, TestModel(custom_output_args={"vuln_class": "rce"}))
    assert FindingFacts.model_validate(out).vuln_class == "rce"


async def test_rule_out_returns_result(deps):
    out = await run_rule_out(deps, TestModel(custom_output_args={"killed": False}))
    assert RuleOutResult.model_validate(out).killed is False


async def test_trace_path_returns_reachability(deps):
    out = await run_trace_path(deps, TestModel(custom_output_args={"reached": "yes"}))
    assert DeepReachability.model_validate(out).reached == "yes"


async def test_plan_exploit_returns_plan(deps):
    out = await run_plan_exploit(deps, TestModel(custom_output_args={"no_credible_exploit": True}))
    assert ExploitPlan.model_validate(out).no_credible_exploit is True


# ── per-tier token ceilings (the runaway-cost guard must not clip the 1M tiers) ──


class _Out:
    def model_dump(self):
        return {}


class _Result:
    output = _Out()


async def _capture_token_limit(monkeypatch, runner) -> int:
    """Run *runner* with run_agent_with_retry stubbed, returning the
    total_tokens_limit it was handed."""
    captured: dict[str, int] = {}

    async def _fake(agent, prompt, deps, *, attempts=12, total_tokens_limit=None):
        captured["limit"] = total_tokens_limit
        return _Result()

    monkeypatch.setattr(dd_agents, "run_agent_with_retry", _fake)
    deps = WorkspaceDeps(workspace_id="t", workspace_dir="/tmp", finding={}, prior_context={})
    await runner(deps, TestModel())
    return captured["limit"]


async def test_cheap_stages_get_the_cheap_ceiling(monkeypatch):
    # gather_facts / rule_out run on haiku (200K window) — capped below it.
    for runner in (run_gather_facts, run_rule_out):
        assert await _capture_token_limit(monkeypatch, runner) == DEEP_DIVE_TOKEN_LIMIT_CHEAP


async def test_strong_stages_get_the_strong_ceiling(monkeypatch):
    # trace_path / plan_exploit run on sonnet (1M window) — a higher cap so a deep
    # stage isn't clipped into `incomplete` (the recall regression a flat cap caused).
    for runner in (run_trace_path, run_plan_exploit):
        assert await _capture_token_limit(monkeypatch, runner) == DEEP_DIVE_TOKEN_LIMIT_STRONG


def test_token_ceilings_are_tiered_and_window_aware():
    # The cheap cap must sit below haiku's 200K window (bounds runaway + avoids the
    # overflow-400); the strong cap must exceed it (room for a deep 1M-window stage).
    assert DEEP_DIVE_TOKEN_LIMIT_CHEAP < 200_000
    assert DEEP_DIVE_TOKEN_LIMIT_STRONG > DEEP_DIVE_TOKEN_LIMIT_CHEAP


def test_malformed_token_limit_env_does_not_crash(monkeypatch):
    # A typo in the override must fall back to the default, not ValueError at import.
    monkeypatch.setenv("X_BAD", "200k")
    assert dd_agents._int_env("X_BAD", 123) == 123
    monkeypatch.setenv("X_BAD", "-5")
    assert dd_agents._int_env("X_BAD", 123) == 123
    monkeypatch.setenv("X_BAD", "50000")
    assert dd_agents._int_env("X_BAD", 123) == 50000


# ── deterministic challenge resolution ──────────────────────────────────────


def _rev(verdict, lens="reachability"):
    return ChallengeReviewer(lens=lens, verdict=verdict)


def test_resolve_all_hold():
    c = resolve_challenge([_rev("holds"), _rev("holds"), _rev("holds")], "real")
    assert c.verdict_holds is True
    assert c.downgraded_verdict is None
    assert c.confidence_adjustment == 0.0


def test_resolve_majority_refuted_downgrades():
    c = resolve_challenge([_rev("refuted"), _rev("refuted"), _rev("holds")], "real")
    assert c.verdict_holds is False
    assert c.downgraded_verdict == "needs_review"
    assert c.confidence_adjustment < 0


def test_resolve_tie_holds_but_caps_confidence():
    c = resolve_challenge([_rev("refuted"), _rev("holds")], "real")
    assert c.verdict_holds is True
    assert c.downgraded_verdict is None
    assert c.confidence_adjustment < 0


def test_resolve_empty_holds():
    c = resolve_challenge([], "real")
    assert c.verdict_holds is True


async def test_challenge_panel_runs_all_lenses(deps):
    c = await run_challenge_panel(
        deps, TestModel(custom_output_args={"lens": "x", "verdict": "holds"}), "real"
    )
    assert isinstance(c, Challenge)
    assert c.verdict_holds is True
    assert len(c.reviewers) == len(CHALLENGE_LENSES)
    # The lens is pinned by construction, not the model's choice.
    assert {r.lens for r in c.reviewers} == set(CHALLENGE_LENSES)


# ── disproof challenge: the symmetric gate that can't false-clear ────────────


def test_resolve_disproof_all_hold_clears():
    c = resolve_disproof(
        [_rev("holds", "bypass"), _rev("holds", "scope"), _rev("holds", "phantom")]
    )
    assert c.verdict_holds is True
    assert c.downgraded_verdict is None


def test_resolve_disproof_bypass_refute_vetoes_clear():
    # The bypass lens found a concrete bypass = the finding is REAL. It must NOT be
    # outvoted (plain majority false-cleared mlflow-pathtrav-vulnerable this way).
    c = resolve_disproof(
        [_rev("refuted", "bypass"), _rev("holds", "scope"), _rev("holds", "phantom")]
    )
    assert c.verdict_holds is False
    assert c.downgraded_verdict == "needs_review"


def test_resolve_disproof_lone_scope_nitpick_still_clears():
    # bypass holds (no bypass) + a single scope nitpick → majority clears.
    c = resolve_disproof(
        [_rev("holds", "bypass"), _rev("refuted", "scope"), _rev("holds", "phantom")]
    )
    assert c.verdict_holds is True


def test_resolve_disproof_majority_refute_blocks_clear():
    c = resolve_disproof(
        [_rev("holds", "bypass"), _rev("refuted", "scope"), _rev("refuted", "phantom")]
    )
    assert c.verdict_holds is False
    assert c.downgraded_verdict == "needs_review"


def test_resolve_disproof_empty_does_not_clear():
    c = resolve_disproof([])
    assert c.verdict_holds is False


async def test_disproof_panel_runs_all_lenses(deps):
    c = await run_disproof_challenge(
        deps, TestModel(custom_output_args={"lens": "x", "verdict": "holds"})
    )
    assert isinstance(c, Challenge)
    assert c.verdict_holds is True  # all hold → guard upheld
    assert {r.lens for r in c.reviewers} == set(DISPROOF_LENSES)
