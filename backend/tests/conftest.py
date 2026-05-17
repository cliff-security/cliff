"""Shared test fixtures."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from cliff.engine.models import SessionDetail, SessionSummary


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(autouse=True)
def _stub_onboarding_repo_probe():
    """Don't hit api.github.com during tests.

    ``/api/onboarding/repo`` probes GitHub for display metadata. Tests that
    aren't specifically exercising that probe should get an instant ``None``
    so the suite stays offline and fast.
    """
    with patch(
        "cliff.api.routes.onboarding._probe_repo_metadata",
        AsyncMock(return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# OpenCode mocks (existing tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_opencode_process():
    """Mock the OpenCode process manager so tests don't need a real server."""
    with (
        patch("cliff.api.routes.health.opencode_process") as mock_proc,
        patch("cliff.api.routes.health.opencode_client") as mock_health_client,
    ):
        mock_proc.health_check = AsyncMock(return_value=True)
        mock_proc.is_running = True
        mock_proc.is_healthy = True
        mock_health_client.get_config = AsyncMock(
            return_value={"model": "openai/gpt-4.1-nano"}
        )
        yield mock_proc


@pytest.fixture
def mock_opencode_client():
    """Mock the OpenCode HTTP client in all route modules."""
    with (
        patch("cliff.api.routes.sessions.opencode_client") as mock_sessions,
        patch("cliff.api.routes.chat.opencode_client") as mock_chat,
    ):
        # Default behaviors
        for m in (mock_sessions, mock_chat):
            m.create_session = AsyncMock(
                return_value=SessionSummary(id="test-session-123")
            )
            m.list_sessions = AsyncMock(
                return_value=[SessionSummary(id="test-session-123")]
            )
            m.get_session = AsyncMock(
                return_value=SessionDetail(id="test-session-123", messages=[])
            )
            m.send_message = AsyncMock(return_value={"status": "ok"})
            m.stream_events = AsyncMock()
            m.health_check = AsyncMock(return_value=True)

        # Return both mocks so tests can override per-module
        yield type("Mocks", (), {
            "sessions": mock_sessions,
            "chat": mock_chat,
        })()


@pytest.fixture
def client(mock_opencode_process, mock_opencode_client):
    """FastAPI test client with mocked dependencies."""
    from cliff.main import app

    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Database fixtures (Phase 3+)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_client():
    """Async HTTP client backed by an in-memory SQLite database.

    Uses httpx.AsyncClient + ASGITransport to keep everything in a single
    event loop — avoids the cross-loop issues with sync TestClient + async db.

    Injects mock process_pool and context_builder on app.state so workspace
    routes that access request.app.state don't crash.
    """
    from cliff.db.connection import close_db, init_db
    from cliff.main import app

    app.router.lifespan_context = _noop_lifespan
    await init_db(":memory:")

    # Mock app.state objects for workspace routes (Layer 3+4).
    # The mocks must produce real Workspace objects so FastAPI response
    # validation passes. We delegate to raw DB functions.
    from cliff.db.repo_finding import mark_started_on_workspace_create
    from cliff.db.repo_sidebar import mark_plan_approved as _raw_mark_approved
    from cliff.db.repo_workspace import (
        create_workspace as raw_create,
    )
    from cliff.db.repo_workspace import (
        delete_workspace as raw_delete,
    )
    from cliff.models import WorkspaceCreate

    mock_pool = AsyncMock()
    mock_pool.stop = AsyncMock()
    app.state.process_pool = mock_pool

    async def _mock_create_workspace(db, finding, **_kwargs):
        data = WorkspaceCreate(finding_id=finding.id)
        ws = await raw_create(db, data)
        # Mirror real context_builder: PRD-0006 / IMPL-0006 root-cause fix.
        await mark_started_on_workspace_create(db, finding.id)
        return ws

    async def _mock_delete_workspace(db, workspace_id):
        return await raw_delete(db, workspace_id)

    async def _mock_mark_plan_approved(db, workspace_id):
        # Tests don't have a real workspace directory, so we only flip
        # the SQLite store (the filesystem mirror exercised by real
        # context_builder is covered by integration tests).
        sidebar = await _raw_mark_approved(db, workspace_id)
        return sidebar.plan if sidebar and sidebar.plan else None

    mock_builder = AsyncMock()
    mock_builder.create_workspace = AsyncMock(side_effect=_mock_create_workspace)
    mock_builder.delete_workspace = AsyncMock(side_effect=_mock_delete_workspace)
    mock_builder.mark_plan_approved = AsyncMock(side_effect=_mock_mark_plan_approved)
    app.state.context_builder = mock_builder

    # Reset integration layer state (may be stale from other tests).
    app.state.vault = None
    app.state.audit_logger = None
    app.state.assessment_tasks = set()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Drain any assessment background tasks before closing the DB so they don't
    # race a closed connection (EXEC-0002 Session B).
    pending = list(getattr(app.state, "assessment_tasks", set()))
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    app.state.assessment_tasks = set()

    await close_db()
