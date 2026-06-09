"""Shared setup for the real-LLM agent evals.

Thin re-export of the canonical selection policy in ``cliff.evals.models`` —
which lives in the public package (not ``tests/``) so the in-repo live tests AND
the private ``cliff-os/eval`` runner share ONE policy and can't drift. Live test
modules are skip-gated on a runnable model being available (see ``conftest.py``).
"""

from __future__ import annotations

from cliff.evals.models import harvest_env, select_eval_model

LLM_ENV = harvest_env()
# Resolved at import; only *used* by tests that are skip-gated on a runnable
# model, so the last-resort fallback is just to keep this non-None at import.
LLM_MODEL = select_eval_model() or "openai/gpt-4o-mini"
