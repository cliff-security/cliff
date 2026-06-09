"""Agent test fixtures.

Most agent tests drive the Pydantic AI runtime with a ``FunctionModel`` /
``TestModel`` and need no network — those must run in keyless CI so a runtime
regression isn't masked. Only the two files that call a *real* LLM are skipped
when no API key is set.
"""

from __future__ import annotations

import pytest

from cliff.evals.models import eval_runnable

# Gate live-LLM tests on whether a model actually resolves (CLIFF_EVAL_MODEL
# override or a configured provider) — derived from the SAME policy the runner
# uses, so the gate can't say "runnable" while eval_model picks a model with no
# key (e.g. an Ollama-only host that would otherwise hard-error, not skip).
_skip_no_key = pytest.mark.skipif(
    not eval_runnable(),
    reason="No runnable eval model (set a provider key or CLIFF_EVAL_MODEL)",
)

# Files whose every test hits a real LLM (the live evals). Everything else
# under tests/agents/ runs against FunctionModel/TestModel and stays in CI.
_LIVE_LLM_FILES = (
    "test_normalizer_agent",
    "test_plain_description_eval",
    "test_evals_finding_enricher",
)


def pytest_collection_modifyitems(items):
    """Mark agent tests; skip only the live-LLM files when no key is set."""
    for item in items:
        path = str(item.fspath)
        if "/agents/" not in path:
            continue
        item.add_marker(pytest.mark.agent)
        if any(name in path for name in _LIVE_LLM_FILES):
            item.add_marker(_skip_no_key)
