"""Agent integration test fixtures — real OpenCode subprocess + real LLM.

These tests call the actual LLM via OpenCode. They require:
1. OpenCode binary installed (via scripts/install-opencode.sh)
2. OPENAI_API_KEY set in the environment

Run with: uv run pytest tests/agents/ -v
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from cliff.config import settings
from cliff.engine.process import OpenCodeProcess

try:
    from shutil import which
except ImportError:
    which = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_opencode_available = settings.opencode_binary_path.exists() or (
    which is not None and which("opencode") is not None
)
_api_key_set = bool(
    os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
)

_skip_no_binary = pytest.mark.skipif(
    not _opencode_available, reason="OpenCode binary not found"
)
_skip_no_key = pytest.mark.skipif(
    not _api_key_set, reason="No LLM API key set (OPENAI_API_KEY or ANTHROPIC_API_KEY)"
)


def pytest_collection_modifyitems(items):
    """Mark all items in this directory as agent tests and apply skip conditions."""
    for item in items:
        if "/agents/" in str(item.fspath):
            item.add_marker(pytest.mark.agent)
            item.add_marker(_skip_no_binary)
            item.add_marker(_skip_no_key)


# ---------------------------------------------------------------------------
# Session-scoped OpenCode server
# ---------------------------------------------------------------------------

_process: OpenCodeProcess | None = None


@pytest.fixture(scope="session", autouse=True)
def opencode_server():
    """Start a real OpenCode server for the agent test session."""
    global _process
    _process = OpenCodeProcess()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_process.start())
        # Extra wait for OpenCode to be fully ready
        time.sleep(2)
        yield _process
    finally:
        loop.run_until_complete(_process.stop())
        loop.close()
        _process = None


@pytest.fixture(autouse=True)
def reset_client(opencode_server):
    """Reset the singleton OpenCode client before each test."""
    import cliff.integrations.normalizer as normalizer_mod
    from cliff.engine.client import OpenCodeClient

    fresh_client = OpenCodeClient(base_url=settings.opencode_url)
    normalizer_mod.opencode_client = fresh_client
    yield
