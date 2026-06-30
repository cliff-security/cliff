"""Eval pricing table — the judge (opus) tier must be priced.

The Deep dive escalates to opus for the challenge panels (model_tiers._LINEUP).
If opus is unpriced, ``estimate_cost_usd`` returns None for those calls, which
makes the eval runner's ``_TokenAccumulator.total_usd()`` return None and
silently disables its ``$`` budget cap (``acc.total_usd() or 0.0`` reads $0).
These lock the whole anthropic lineup as priced so the cap can never go blind.
"""

from __future__ import annotations

import pytest

from cliff.evals.pricing import estimate_cost_usd


def test_opus_judge_tier_is_priced():
    # $5 / MTok input + $25 / MTok output → 1M of each = $30.
    cost = estimate_cost_usd("anthropic/claude-opus-4-8", 1_000_000, 1_000_000)
    assert cost is not None
    assert cost == pytest.approx(30.0)


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-opus-4-8",
        "openrouter/anthropic/claude-opus-4.8",
    ],
)
def test_full_lineup_is_priced(model_id):
    # Every tier the Deep dive can reach must return a non-None estimate, or the
    # accumulator's all-or-nothing total_usd() collapses to None on first use.
    assert estimate_cost_usd(model_id, 1000, 500) is not None


def test_opus_priced_above_sonnet():
    opus = estimate_cost_usd("anthropic/claude-opus-4-8", 1_000_000, 0)
    sonnet = estimate_cost_usd("anthropic/claude-sonnet-4-6", 1_000_000, 0)
    assert opus is not None and sonnet is not None
    assert opus > sonnet  # opus must not be mispriced against a cheaper sibling
