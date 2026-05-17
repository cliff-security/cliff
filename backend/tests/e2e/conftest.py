"""E2E test fixtures — real OpenCode subprocess + real FastAPI app."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from shutil import which

import pytest
from fastapi.testclient import TestClient

from cliff.config import settings
from cliff.engine.process import OpenCodeProcess

# Skip all e2e tests if prerequisites are missing
_opencode_available = settings.opencode_binary_path.exists() or which("opencode") is not None
_api_key_set = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))

_skip_no_binary = pytest.mark.skipif(
    not _opencode_available, reason="OpenCode binary not found"
)
_skip_no_key = pytest.mark.skipif(
    not _api_key_set, reason="No LLM API key set (OPENAI_API_KEY)"
)


def pytest_collection_modifyitems(items):
    """Mark all items in this directory as e2e and apply skip conditions."""
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
            item.add_marker(_skip_no_binary)
            item.add_marker(_skip_no_key)


@asynccontextmanager
async def _noop_lifespan(app):
    yield


# Session-scoped OpenCode process
_process: OpenCodeProcess | None = None


@pytest.fixture(scope="session", autouse=True)
def opencode_server():
    """Start a real OpenCode server for the e2e test session."""
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


@pytest.fixture
def app_client(opencode_server):
    """FastAPI TestClient with real OpenCode running underneath.

    Each test gets a fresh TestClient to avoid connection pool issues.
    """
    from cliff.db.connection import close_db, init_db
    from cliff.engine.client import OpenCodeClient
    from cliff.main import app

    # Skip lifespan — OpenCode is already running via session fixture
    app.router.lifespan_context = _noop_lifespan

    # Initialize in-memory DB for settings endpoints
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
    loop.run_until_complete(init_db(":memory:"))

    # Reset the singleton client to avoid stale connections
    import cliff.api.routes.chat as chat_mod
    import cliff.api.routes.sessions as sessions_mod

    fresh_client = OpenCodeClient(base_url=settings.opencode_url)
    sessions_mod.opencode_client = fresh_client
    chat_mod.opencode_client = fresh_client

    with TestClient(app) as client:
        yield client

    loop.run_until_complete(close_db())
