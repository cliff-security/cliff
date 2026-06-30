"""Eval model selection + the live-spend opt-in gate.

``live_eval_enabled`` is the single policy both the in-repo live-LLM test gate
(tests/agents/conftest.py) and the private eval runner consult before spending
real provider credit. A provider key alone must NOT enable spend — that was the
hole that let a key exported for the runner silently turn ``pytest tests/agents/``
into a metered run.
"""

from __future__ import annotations

from cliff.evals.models import eval_runnable, live_eval_enabled, select_eval_model


def test_key_present_resolves_a_model():
    src = {"ANTHROPIC_API_KEY": "sk-ant-xxx"}
    assert select_eval_model(src) == "anthropic/claude-haiku-4-5"
    assert eval_runnable(src) is True


def test_live_eval_requires_opt_in_even_with_key():
    # A key resolves a model (runnable), but spend is still OFF without the
    # explicit opt-in. This is the prevention: key != permission to spend.
    src = {"ANTHROPIC_API_KEY": "sk-ant-xxx"}
    assert eval_runnable(src) is True
    assert live_eval_enabled(src) is False


def test_live_eval_enabled_with_opt_in_and_key():
    src = {"ANTHROPIC_API_KEY": "sk-ant-xxx", "CLIFF_LIVE_EVAL": "1"}
    assert live_eval_enabled(src) is True


def test_opt_in_without_a_runnable_model_is_still_disabled():
    # Opt-in alone can't conjure a model — nothing to run, nothing to spend.
    src = {"CLIFF_LIVE_EVAL": "1"}
    assert eval_runnable(src) is False
    assert live_eval_enabled(src) is False


def test_opt_in_must_be_exactly_one():
    assert live_eval_enabled({"ANTHROPIC_API_KEY": "k", "CLIFF_LIVE_EVAL": "true"}) is False
    assert live_eval_enabled({"ANTHROPIC_API_KEY": "k", "CLIFF_LIVE_EVAL": "0"}) is False
    assert live_eval_enabled({"ANTHROPIC_API_KEY": "k", "CLIFF_LIVE_EVAL": " 1 "}) is True
