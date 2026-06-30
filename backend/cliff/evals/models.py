"""Eval model + provider selection (ADR-0050).

Lives in the public ``cliff.evals`` package (not ``tests/``) so the in-repo
live test AND the private ``cliff-os/eval`` runner share ONE selection policy —
otherwise the two lanes can silently run different models and mask each other's
regressions.

``select_eval_model`` returns the cheap-but-capable model for whichever provider
is configured, or ``None`` when nothing runnable is available. The live-test skip
gate is exactly "is there a runnable model?" — so it can't diverge from what the
runner will actually use (the conftest-gate-vs-eval_model bug this replaces).
"""

from __future__ import annotations

import os

# Cheap-capable default per provider, keyed by the env var that selects it.
# Order matters: prefer the production default (Anthropic haiku) first.
_PROVIDER_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
    ("OPENROUTER_API_KEY", "openrouter/anthropic/claude-haiku-4.5"),
    ("GEMINI_API_KEY", "google/gemini-2.5-flash"),
    # Ollama needs a locally-pulled model name we can't assume, so it is NOT
    # auto-selected — set CLIFF_EVAL_MODEL=ollama/<model> explicitly.
)


def harvest_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """The provider credentials the model factory reads (``*_API_KEY`` /
    ``*_BASE_URL``), harvested from the host env."""
    env = source if source is not None else os.environ
    return {k: v for k, v in env.items() if k.endswith(("_API_KEY", "_BASE_URL"))}


def select_eval_model(source: dict[str, str] | None = None) -> str | None:
    """The model the eval should run, or ``None`` if nothing is runnable.

    ``CLIFF_EVAL_MODEL`` overrides (the operator owns matching the key); else the
    first configured provider's cheap default. Match the production default
    (Anthropic haiku) so the eval predicts customer experience.
    """
    env = source if source is not None else os.environ
    if override := env.get("CLIFF_EVAL_MODEL"):
        return override
    for key_var, model in _PROVIDER_DEFAULTS:
        if env.get(key_var):
            return model
    return None


def eval_runnable(source: dict[str, str] | None = None) -> bool:
    """True iff a live eval can actually run (a model resolves). Kept identical
    to ``select_eval_model`` so they never diverge."""
    return select_eval_model(source) is not None


def live_eval_enabled(source: dict[str, str] | None = None) -> bool:
    """True iff live-LLM evals may run *and spend real credit*.

    Requires BOTH an explicit opt-in (``CLIFF_LIVE_EVAL=1``) AND a runnable
    model. A provider key alone is deliberately NOT enough: a key exported in
    the shell (for the eval runner, or sitting in the host profile) must never
    silently turn a plain ``pytest`` run into a metered one. This is the gate
    the live-LLM test files skip on — spend is opt-in, not opt-out."""
    env = source if source is not None else os.environ
    opt_in = env.get("CLIFF_LIVE_EVAL", "").strip() == "1"
    return opt_in and eval_runnable(source)


__all__ = ["eval_runnable", "harvest_env", "live_eval_enabled", "select_eval_model"]
