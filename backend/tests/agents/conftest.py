"""Agent test fixtures.

Most agent tests drive the Pydantic AI runtime with a ``FunctionModel`` /
``TestModel`` and need no network — but the live eval (``test_plain_description_eval``)
calls a real LLM, so the whole directory is skipped when no API key is set.
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


def pytest_collection_modifyitems(items):
    """Mark all items in this directory as agent tests and skip when no key."""
    for item in items:
        if "/agents/" in str(item.fspath):
            item.add_marker(pytest.mark.agent)
            item.add_marker(_skip_no_key)
