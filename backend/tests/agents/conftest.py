"""Agent test fixtures.

Most agent tests drive the Pydantic AI runtime with a ``FunctionModel`` /
``TestModel`` and need no network — those must run in keyless CI so a runtime
regression isn't masked. The handful of files that call a *real* LLM (and so
SPEND credit) are skipped by default and only run under an explicit
``CLIFF_LIVE_EVAL=1`` opt-in — a provider key alone is not enough to trigger
spend (see ``_skip_live`` below).
"""

from __future__ import annotations

import pytest

from cliff.evals.models import live_eval_enabled

# Live-LLM tests SPEND real provider credit. They are skipped by default — even
# when a provider key is present in the environment — and only run under an
# explicit CLIFF_LIVE_EVAL=1 opt-in. The policy lives in cliff.evals.models
# (`live_eval_enabled`) so the in-repo test gate and the private eval runner
# share ONE definition of "may we spend?".
_skip_live = pytest.mark.skipif(
    not live_eval_enabled(),
    reason="Live-LLM eval skipped (it spends real credit) — set CLIFF_LIVE_EVAL=1 "
    "plus a provider key / CLIFF_EVAL_MODEL to opt in.",
)

# Files whose every test hits a real LLM (the live evals). Everything else
# under tests/agents/ runs against FunctionModel/TestModel and stays in CI.
_LIVE_LLM_FILES = (
    "test_normalizer_agent",
    "test_plain_description_eval",
    "test_evals_finding_enricher",
    "test_evals_report_triager",
)


def pytest_collection_modifyitems(items):
    """Mark agent tests; skip only the live-LLM files when no key is set."""
    for item in items:
        path = str(item.fspath)
        if "/agents/" not in path:
            continue
        item.add_marker(pytest.mark.agent)
        if any(name in path for name in _LIVE_LLM_FILES):
            item.add_marker(_skip_live)
