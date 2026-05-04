"""Tests for the PRD-0006 Phase 2 ``user_note`` extension on agent execute
(IMPL-0007 §B4).

Adds an optional ``user_note`` body field to
``POST /workspaces/{id}/agents/{agent_type}/execute``. When the agent type is
``remediation_planner`` and the note is set, it is forwarded into the prompt
so the planner re-runs with the user's refinement instructions in scope.

The route stays open to all agents — non-planner agents simply ignore the
note. Empty / missing note behaves identically to today's call (regression
guard for existing callers).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from opensec.api.routes.agent_execution import router
from opensec.db.connection import get_db
from opensec.models import Workspace


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def app(mock_db):
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")

    async def _mock_get_db():
        yield mock_db

    test_app.dependency_overrides[get_db] = _mock_get_db
    test_app.state.agent_executor = AsyncMock()
    test_app.state.context_builder = AsyncMock()
    test_app.state.opencode_client = AsyncMock()
    return test_app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _make_workspace(workspace_id: str = "ws-1") -> Workspace:
    return Workspace(
        id=workspace_id,
        finding_id="f-1",
        state="open",
        workspace_dir="/tmp/workspaces/ws-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def _wait_for_executor_call(executor: AsyncMock, max_iters: int = 50) -> None:
    """The route fires the executor in a background task; give it a tick."""
    for _ in range(max_iters):
        if executor.execute.await_count >= 1:
            return
        await asyncio.sleep(0.01)


async def test_user_note_forwarded_to_executor(app, client) -> None:
    """When ``user_note`` is set, the executor receives it as a kwarg."""
    executor = app.state.agent_executor
    executor.check_not_busy = AsyncMock(return_value=None)
    executor.execute = AsyncMock(return_value=None)
    executor.get_active_run_id = lambda ws_id: "run-1"
    executor.push_permission_event = lambda *a, **k: None

    with patch(
        "opensec.api.routes.agent_execution.get_workspace",
        return_value=_make_workspace(),
    ), patch(
        "opensec.api.routes.agent_execution._resolve_repo_env_vars",
        new=AsyncMock(return_value={}),
    ):
        resp = await client.post(
            "/api/workspaces/ws-1/agents/remediation_planner/execute",
            json={"user_note": "Skip the wrapper change in lib/normalize.ts."},
        )

    assert resp.status_code == 202, resp.text
    await _wait_for_executor_call(executor)
    assert executor.execute.await_count == 1
    _args, kwargs = executor.execute.await_args
    assert kwargs.get("user_note") == "Skip the wrapper change in lib/normalize.ts."


async def test_missing_user_note_behaves_like_phase_1(app, client) -> None:
    """No body = behaves identically to today's empty-body call."""
    executor = app.state.agent_executor
    executor.check_not_busy = AsyncMock(return_value=None)
    executor.execute = AsyncMock(return_value=None)
    executor.get_active_run_id = lambda ws_id: "run-1"
    executor.push_permission_event = lambda *a, **k: None

    with patch(
        "opensec.api.routes.agent_execution.get_workspace",
        return_value=_make_workspace(),
    ), patch(
        "opensec.api.routes.agent_execution._resolve_repo_env_vars",
        new=AsyncMock(return_value={}),
    ):
        resp = await client.post(
            "/api/workspaces/ws-1/agents/remediation_planner/execute"
        )

    assert resp.status_code == 202, resp.text
    await _wait_for_executor_call(executor)
    assert executor.execute.await_count == 1
    _args, kwargs = executor.execute.await_args
    assert kwargs.get("user_note") in (None, "")


async def test_user_note_too_long_returns_422(app, client) -> None:
    with patch(
        "opensec.api.routes.agent_execution.get_workspace",
        return_value=_make_workspace(),
    ):
        resp = await client.post(
            "/api/workspaces/ws-1/agents/remediation_planner/execute",
            json={"user_note": "x" * 2001},
        )
    assert resp.status_code == 422


def test_user_note_appears_in_planner_prompt() -> None:
    """The planner's runtime prompt must include the user's note as an
    authoritative refinement block."""
    from opensec.agents.executor import build_agent_prompt

    finding = {
        "id": "f-1",
        "source_type": "tenable",
        "source_id": "vuln-001",
        "title": "CVE-2024-1234",
        "description": "RCE in libfoo",
        "raw_severity": "high",
    }

    prompt_with_note = build_agent_prompt(
        "remediation_planner",
        finding=finding,
        user_note="Skip the wrapper change in lib/normalize.ts.",
    )
    prompt_without = build_agent_prompt(
        "remediation_planner",
        finding=finding,
    )

    assert "Skip the wrapper change in lib/normalize.ts." in prompt_with_note
    assert "User refinement" in prompt_with_note
    assert "Skip the wrapper change" not in prompt_without
    assert "User refinement" not in prompt_without

    # Empty / None note must not introduce a refinement block.
    prompt_empty = build_agent_prompt(
        "remediation_planner", finding=finding, user_note=""
    )
    assert "User refinement" not in prompt_empty
