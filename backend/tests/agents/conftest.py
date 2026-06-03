"""Agent test fixtures.

Most agent tests drive the Pydantic AI runtime with a ``FunctionModel`` /
``TestModel`` and need no network — those must run in keyless CI so a runtime
regression isn't masked. Only the two files that call a *real* LLM are skipped
when no API key is set.
"""

from __future__ import annotations

import os

import pytest

_api_key_set = bool(
    os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
)

_skip_no_key = pytest.mark.skipif(
    not _api_key_set, reason="No LLM API key set (OPENAI_API_KEY or ANTHROPIC_API_KEY)"
)

# Files whose every test hits a real LLM (the live evals). Everything else
# under tests/agents/ runs against FunctionModel/TestModel and stays in CI.
_LIVE_LLM_FILES = ("test_normalizer_agent", "test_plain_description_eval")


def pytest_collection_modifyitems(items):
    """Mark agent tests; skip only the live-LLM files when no key is set."""
    for item in items:
        path = str(item.fspath)
        if "/agents/" not in path:
            continue
        item.add_marker(pytest.mark.agent)
        if any(name in path for name in _LIVE_LLM_FILES):
            item.add_marker(_skip_no_key)
