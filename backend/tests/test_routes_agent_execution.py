"""Tests for the agent execution API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from opensec.agents.errors import AgentBusyError
from opensec.agents.executor import AgentExecutionResult
from opensec.agents.output_parser import ParseResult
from opensec.api.routes.agent_execution import router
from opensec.db.connection import get_db
from opensec.models import Workspace

# ---------------------------------------------------------------------------
# App fixture with mock DB dependency
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def app(mock_db):
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")

    # Override get_db dependency
    async def _mock_get_db():
        yield mock_db

    test_app.dependency_overrides[get_db] = _mock_get_db

    # Mock executor and context builder
    test_app.state.agent_executor = AsyncMock()
    test_app.state.context_builder = AsyncMock()

    return test_app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _make_workspace(workspace_id="ws-1"):
    return Workspace(
        id=workspace_id,
        finding_id="f-1",
        state="open",
        workspace_dir="/tmp/workspaces/ws-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_execution_result(agent_type="finding_enricher", status="completed"):
    return AgentExecutionResult(
        agent_run_id="run-123",
        agent_type=agent_type,
        status=status,
        parse_result=ParseResult(success=True, raw_text="test"),
    )


# ---------------------------------------------------------------------------
# Execute endpoint
# ---------------------------------------------------------------------------


class TestExecuteEndpoint:
    @pytest.mark.asyncio
    async def test_execute_returns_202(self, app, client):
        """Execute returns 202 immediately (background task)."""
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock()
        executor.get_active_run_id = lambda ws_id: "run-123"
        executor.execute = AsyncMock(return_value=_make_execution_result())

        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/finding_enricher/execute"
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["agent_type"] == "finding_enricher"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_execute_workspace_not_found(self, client):
        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=None,
        ):
            resp = await client.post(
                "/api/workspaces/ws-999/agents/finding_enricher/execute"
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_invalid_agent_type(self, client):
        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/invalid_agent/execute"
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_execute_busy_returns_409(self, app, client):
        """Pre-flight busy check returns 409 before launching background task."""
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock(side_effect=AgentBusyError("busy"))

        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/finding_enricher/execute"
            )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Suggest-next endpoint
# ---------------------------------------------------------------------------


class TestSuggestNextEndpoint:
    @pytest.mark.asyncio
    async def test_suggest_enricher(self, app, client):
        app.state.context_builder.get_context_snapshot.return_value = {
            "finding": {"id": "f-1"},
            "enrichment": None,
            "ownership": None,
            "exposure": None,
            "plan": None,
            "validation": None,
            "agent_run_history": [],
        }

        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ):
            resp = await client.get(
                "/api/workspaces/ws-1/pipeline/suggest-next"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_type"] == "finding_enricher"
        assert data["priority"] == "recommended"

    @pytest.mark.asyncio
    async def test_suggest_review_pr_when_complete(self, app, client):
        app.state.context_builder.get_context_snapshot.return_value = {
            "finding": {"id": "f-1"},
            "enrichment": {"normalized_title": "T"},
            "ownership": {"recommended_owner": "A"},
            "exposure": {"recommended_urgency": "high"},
            "evidence": {"affected_files": [], "fix_safety": "safe_bump"},
            "plan": {"plan_steps": ["1"]},
            "remediation": {"status": "pr_created", "pr_url": "https://github.com/..."},
            "validation": {"verdict": "fixed", "recommendation": "close"},
            "agent_run_history": [],
        }

        with patch(
            "opensec.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ):
            resp = await client.get(
                "/api/workspaces/ws-1/pipeline/suggest-next"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_type"] is None
        assert data["action_type"] == "review_pr"


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------


class TestCancelEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_running_agent(self, client):
        from opensec.models import AgentRun

        mock_run = AgentRun(
            id="run-1",
            workspace_id="ws-1",
            agent_type="finding_enricher",
            status="running",
        )

        with (
            patch(
                "opensec.api.routes.agent_execution.get_agent_run",
                return_value=mock_run,
            ),
            patch(
                "opensec.api.routes.agent_execution.update_agent_run",
            ),
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agent-runs/run-1/cancel"
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_400(self, client):
        from opensec.models import AgentRun

        mock_run = AgentRun(
            id="run-1",
            workspace_id="ws-1",
            agent_type="finding_enricher",
            status="completed",
        )

        with patch(
            "opensec.api.routes.agent_execution.get_agent_run",
            return_value=mock_run,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agent-runs/run-1/cancel"
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Permission approval endpoint — wires user click → executor.approve_tool /
# deny_tool. Trust-critical: if approve/deny don't reach the parked
# ``_PendingApproval``, the agent stalls forever.
# ---------------------------------------------------------------------------


class TestPermissionEndpoint:
    @pytest.mark.asyncio
    async def test_approve_calls_executor_approve_tool(self, app, client):
        executor = app.state.agent_executor
        executor.approve_tool = lambda run_id: True

        resp = await client.post(
            "/api/workspaces/ws-1/agent-runs/run-1/permission",
            json={"approved": True},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["agent_run_id"] == "run-1"

    @pytest.mark.asyncio
    async def test_deny_calls_executor_deny_tool(self, app, client):
        executor = app.state.agent_executor
        executor.deny_tool = lambda run_id: True

        resp = await client.post(
            "/api/workspaces/ws-1/agent-runs/run-1/permission",
            json={"approved": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "denied"
        assert body["agent_run_id"] == "run-1"

    @pytest.mark.asyncio
    async def test_no_pending_returns_404(self, app, client):
        executor = app.state.agent_executor
        executor.approve_tool = lambda run_id: False
        executor.deny_tool = lambda run_id: False

        resp = await client.post(
            "/api/workspaces/ws-1/agent-runs/gone/permission",
            json={"approved": True},
        )

        assert resp.status_code == 404
        assert "No pending permission request" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_approve_routed_to_approve_not_deny(self, app, client):
        """Trust guard — make sure ``approved=true`` doesn't accidentally
        wire to deny_tool. Regression catcher for the conditional in
        ``respond_to_permission``."""
        approve_calls = []
        deny_calls = []

        executor = app.state.agent_executor
        executor.approve_tool = lambda run_id: approve_calls.append(run_id) or True
        executor.deny_tool = lambda run_id: deny_calls.append(run_id) or True

        resp = await client.post(
            "/api/workspaces/ws-1/agent-runs/run-77/permission",
            json={"approved": True},
        )

        assert resp.status_code == 200
        assert approve_calls == ["run-77"]
        assert deny_calls == []

    @pytest.mark.asyncio
    async def test_deny_routed_to_deny_not_approve(self, app, client):
        approve_calls = []
        deny_calls = []

        executor = app.state.agent_executor
        executor.approve_tool = lambda run_id: approve_calls.append(run_id) or True
        executor.deny_tool = lambda run_id: deny_calls.append(run_id) or True

        resp = await client.post(
            "/api/workspaces/ws-1/agent-runs/run-88/permission",
            json={"approved": False},
        )

        assert resp.status_code == 200
        assert deny_calls == ["run-88"]
        assert approve_calls == []
