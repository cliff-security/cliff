"""Unit tests for Deep dive model tiering (ADR-0052 §4)."""

from __future__ import annotations

from cliff.agents.runtime.model_tiers import (
    judge_is_independent,
    resolve_tier_model_ids,
)


def test_anthropic_lineup_has_three_distinct_tiers():
    ids = resolve_tier_model_ids("anthropic/claude-haiku-4-5")
    assert ids["cheap"] == "anthropic/claude-haiku-4-5"
    assert ids["strong"] == "anthropic/claude-sonnet-4-6"
    assert ids["judge"] == "anthropic/claude-opus-4-8"
    # judge out-ranks strong → a real second opinion.
    assert ids["cheap"] != ids["strong"] != ids["judge"]


def test_openrouter_keeps_provider_prefix():
    ids = resolve_tier_model_ids("openrouter/anthropic/claude-haiku-4.5")
    assert ids["cheap"].startswith("openrouter/anthropic/")
    assert ids["judge"].startswith("openrouter/anthropic/")
    assert ids["judge"] != ids["strong"]


def test_unknown_provider_falls_back_to_single_model():
    ids = resolve_tier_model_ids("ollama/llama3")
    assert ids["cheap"] == ids["strong"] == ids["judge"] == "ollama/llama3"


def test_no_slash_falls_back():
    ids = resolve_tier_model_ids("weird-id")
    assert set(ids.values()) == {"weird-id"}


def test_judge_independence_signal():
    assert judge_is_independent("anthropic/claude-haiku-4-5") is True
    assert judge_is_independent("ollama/llama3") is False
