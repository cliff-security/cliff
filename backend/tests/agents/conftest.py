"""Agent test fixtures.

Most agent tests drive the Pydantic AI runtime with a ``FunctionModel`` /
``TestModel`` and need no network — those must run in keyless CI so a runtime
regression isn't masked. Only the two files that call a *real* LLM are skipped
when no API key is set.
"""

from __future__ import annotations

import os

import pytest

# Any provider build_model() can use — so a runnable non-OpenAI/Anthropic setup
# (e.g. OPENROUTER_API_KEY + CLIFF_EVAL_MODEL=openrouter/...) doesn't get skipped.
_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "OLLAMA_BASE_URL",  # Ollama authenticates with no key
)
_api_key_set = any(os.environ.get(v) for v in _PROVIDER_ENV_VARS)

_skip_no_key = pytest.mark.skipif(
    not _api_key_set,
    reason=f"No LLM provider configured (one of: {', '.join(_PROVIDER_ENV_VARS)})",
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
