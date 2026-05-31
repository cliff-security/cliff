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

# Isolate the e2e session's OpenCode from any running daemon. Without
# this the e2e suite silently *shares* the daemon's OpenCode on the
# default port 4096 (OpenCodeProcess.start() succeeds as long as the
# port answers — even if the answerer is somebody else's process) and
# inherits its model + config, making the settings/model tests flap
# against whatever the user happened to have selected. Mutating
# ``settings.opencode_port`` at conftest module-import time means the
# session-scoped OpenCodeProcess below starts on 4097 and the fresh
# OpenCodeClient we build per-test in ``app_client`` reads
# ``settings.opencode_url`` with the new port baked in.
_E2E_OPENCODE_PORT = 4097


def _verify_e2e_port_free(port: int) -> None:
    """Refuse to run if ``port`` is already in use.

    The 4097 → 4096 collision we just fixed could silently recur on a
    different port if anything else (another e2e run, an unrelated dev
    process) happens to be listening. Bind-test first; fail loud with
    a clear remediation message so the next person isn't stuck
    debugging a flake.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"e2e OpenCode port {port} is already in use ({exc}). "
                "Stop whatever's listening, or override via "
                "CLIFF_OPENCODE_PORT before invoking pytest."
            ) from exc


# Compute e2e prerequisites first — the port check + settings mutation
# below are e2e-only side effects, and a combined run like
# ``pytest backend/tests`` imports this conftest at collection even when
# e2e tests will be skipped. Gating both behind the availability flags
# keeps a busy port from aborting a unit-only run and keeps the
# settings.opencode_port singleton untouched for non-e2e tests.
_opencode_available = settings.opencode_binary_path.exists() or which("opencode") is not None
_api_key_set = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))

if _opencode_available and _api_key_set:
    # Honour CLIFF_OPENCODE_PORT if the operator pinned a different port;
    # otherwise default to the dedicated e2e port. Bind-test before
    # mutating settings so the failure is at conftest load, not mid-test.
    _E2E_OPENCODE_PORT = int(os.environ.get("CLIFF_OPENCODE_PORT", _E2E_OPENCODE_PORT))
    _verify_e2e_port_free(_E2E_OPENCODE_PORT)
    settings.opencode_port = _E2E_OPENCODE_PORT

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

    # Reset the singleton client to avoid stale connections AND to pick
    # up the e2e-isolated port (see top of file). Every module that did
    # ``from cliff.engine.client import opencode_client`` at import time
    # holds its OWN name binding to the original-port client — rebinding
    # the source module alone doesn't fix them. List of importers comes
    # from ``grep -rn "from cliff.engine.client import opencode_client"
    # backend/cliff/``. ``ai/service.py`` re-imports inside its functions
    # so it's auto-fixed by the source-module rebind; the rest must be
    # rebound explicitly here, or routes like /health and /api/settings
    # will silently hit the original-port client.
    import cliff.api.routes.chat as chat_mod
    import cliff.api.routes.health as health_mod
    import cliff.api.routes.sessions as sessions_mod
    import cliff.api.routes.settings as routes_settings_mod
    import cliff.engine.client as client_mod
    import cliff.engine.config_manager as config_mod
    import cliff.integrations.normalizer as normalizer_mod
    import cliff.main as cliff_main_mod

    fresh_client = OpenCodeClient(base_url=settings.opencode_url)
    client_mod.opencode_client = fresh_client
    sessions_mod.opencode_client = fresh_client
    chat_mod.opencode_client = fresh_client
    config_mod.opencode_client = fresh_client
    health_mod.opencode_client = fresh_client
    routes_settings_mod.opencode_client = fresh_client
    normalizer_mod.opencode_client = fresh_client
    cliff_main_mod.opencode_client = fresh_client

    with TestClient(app) as client:
        yield client

    loop.run_until_complete(close_db())
