"""Shared setup for the real-LLM agent evals (IMPL-0022 PR #3b).

The two live-LLM test modules — ``test_normalizer_agent`` and
``test_plain_description_eval`` — both need the same provider env + a
capable-but-cheap model id. Keeping that selection policy here means it
can't drift between the two files. Both modules are skip-gated on an API
key being present (see ``conftest.py``).
"""

from __future__ import annotations

import os

# Provider credentials for the app-level normalizer, harvested from the host
# env (the same shape the running daemon resolves into a workspace).
LLM_ENV = {
    k: v for k, v in os.environ.items() if k.endswith(("_API_KEY", "_BASE_URL"))
}


def eval_model() -> str:
    """Capable, cheap model for the real-LLM eval (override: ``CLIFF_EVAL_MODEL``)."""
    if override := os.environ.get("CLIFF_EVAL_MODEL"):
        return override
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic/claude-haiku-4-5"
    return "openai/gpt-4o-mini"


LLM_MODEL = eval_model()
