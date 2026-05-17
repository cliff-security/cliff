"""Tests for the agent execution API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from cliff.agents.errors import AgentBusyError
from cliff.agents.executor import AgentExecutionResult
from cliff.agents.output_parser import ParseResult
from cliff.api.routes.agent_execution import router
from cliff.db.connection import get_db
from cliff.integrations.github_app.client import RepoPushAccess
from cliff.models import Workspace

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


def _make_workspace(workspace_id="ws-1", repo_url=None):
    return Workspace(
        id=workspace_id,
        finding_id="f-1",
        state="open",
        workspace_dir="/tmp/workspaces/ws-1",
        repo_url=repo_url,
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
            "cliff.api.routes.agent_execution.get_workspace",
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
            "cliff.api.routes.agent_execution.get_workspace",
            return_value=None,
        ):
            resp = await client.post(
                "/api/workspaces/ws-999/agents/finding_enricher/execute"
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_invalid_agent_type(self, client):
        with patch(
            "cliff.api.routes.agent_execution.get_workspace",
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
            "cliff.api.routes.agent_execution.get_workspace",
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
            "cliff.api.routes.agent_execution.get_workspace",
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
            "cliff.api.routes.agent_execution.get_workspace",
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
        from cliff.models import AgentRun

        mock_run = AgentRun(
            id="run-1",
            workspace_id="ws-1",
            agent_type="finding_enricher",
            status="running",
        )

        with (
            patch(
                "cliff.api.routes.agent_execution.get_agent_run",
                return_value=mock_run,
            ),
            patch(
                "cliff.api.routes.agent_execution.update_agent_run",
            ),
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agent-runs/run-1/cancel"
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_400(self, client):
        from cliff.models import AgentRun

        mock_run = AgentRun(
            id="run-1",
            workspace_id="ws-1",
            agent_type="finding_enricher",
            status="completed",
        )

        with patch(
            "cliff.api.routes.agent_execution.get_agent_run",
            return_value=mock_run,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agent-runs/run-1/cancel"
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Push-token preflight (Q01R / B30 / ADR-0037 / IMPL-0014)
#
# When the user clicks "Approve & generate fix" the route gates the
# remediation_executor agent on a GET /repos/{owner}/{repo} preflight that
# confirms the OAuth token has push access. If the App was misconfigured
# to declare Contents:read only, the device-flow user token cannot push
# regardless of what the user can do with a PAT — and without a gate the
# executor wastes a full run producing local edits that never reach
# GitHub. The preflight surfaces that situation as 412 with a structured
# detail body the side panel can render.
# ---------------------------------------------------------------------------


class TestExecutorPushPreflight:
    @pytest.mark.asyncio
    async def test_executor_blocked_when_token_lacks_push_returns_412(
        self, app, client
    ):
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock(return_value=None)
        executor.get_active_run_id = lambda ws_id: "run-1"
        executor.execute = AsyncMock(return_value=None)

        workspace = _make_workspace(
            repo_url="https://github.com/cliff-security/NodeGoat",
        )
        preflight = AsyncMock(
            return_value=RepoPushAccess(
                can_push=False,
                reason=(
                    "GitHub reports this token has no push permission "
                    "on cliff-security/NodeGoat."
                ),
            )
        )

        with patch(
            "cliff.api.routes.agent_execution.get_workspace",
            return_value=workspace,
        ), patch(
            "cliff.api.routes.agent_execution._resolve_repo_env_vars",
            new=AsyncMock(return_value={
                "GH_TOKEN": "ghu_abc",
                "CLIFF_REPO_URL": "https://github.com/cliff-security/NodeGoat",
            }),
        ), patch(
            "cliff.api.routes.agent_execution.check_repo_push_access",
            new=preflight,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/remediation_executor/execute"
            )

        assert resp.status_code == 412, resp.text
        detail = resp.json()["detail"]
        assert detail["error"] == "github_app_permissions"
        assert "push" in detail["reason"].lower()
        assert detail["remediation_link"]
        # The executor must NOT have been launched.
        assert executor.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_executor_proceeds_when_token_has_push(self, app, client):
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock(return_value=None)
        executor.get_active_run_id = lambda ws_id: "run-1"
        executor.execute = AsyncMock(return_value=None)
        executor.push_permission_event = lambda *a, **k: None

        workspace = _make_workspace(
            repo_url="https://github.com/cliff-security/NodeGoat",
        )
        preflight = AsyncMock(
            return_value=RepoPushAccess(can_push=True, reason="")
        )

        with patch(
            "cliff.api.routes.agent_execution.get_workspace",
            return_value=workspace,
        ), patch(
            "cliff.api.routes.agent_execution._resolve_repo_env_vars",
            new=AsyncMock(return_value={
                "GH_TOKEN": "ghu_abc",
                "CLIFF_REPO_URL": "https://github.com/cliff-security/NodeGoat",
            }),
        ), patch(
            "cliff.api.routes.agent_execution.check_repo_push_access",
            new=preflight,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/remediation_executor/execute"
            )

        assert resp.status_code == 202, resp.text

    @pytest.mark.asyncio
    async def test_non_executor_agent_does_not_run_preflight(self, app, client):
        """The preflight only applies to remediation_executor — running the
        planner or enricher must NOT consume a GitHub API call (and must not
        be gated on push access)."""
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock(return_value=None)
        executor.get_active_run_id = lambda ws_id: "run-1"
        executor.execute = AsyncMock(return_value=None)
        executor.push_permission_event = lambda *a, **k: None

        preflight = AsyncMock(
            return_value=RepoPushAccess(can_push=False, reason="x")
        )

        with patch(
            "cliff.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(),
        ), patch(
            "cliff.api.routes.agent_execution._resolve_repo_env_vars",
            new=AsyncMock(return_value={}),
        ), patch(
            "cliff.api.routes.agent_execution.check_repo_push_access",
            new=preflight,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/remediation_planner/execute"
            )

        assert resp.status_code == 202, resp.text
        assert preflight.await_count == 0

    @pytest.mark.asyncio
    async def test_executor_skips_preflight_when_no_github_token(
        self, app, client
    ):
        """If GH_TOKEN is not configured at all, the preflight can't run
        and we let the executor handle the missing-token case the way it
        always has (its template already errors clearly). Not our job to
        invent a token to call the preflight with."""
        executor = app.state.agent_executor
        executor.check_not_busy = AsyncMock(return_value=None)
        executor.get_active_run_id = lambda ws_id: "run-1"
        executor.execute = AsyncMock(return_value=None)
        executor.push_permission_event = lambda *a, **k: None

        preflight = AsyncMock(
            return_value=RepoPushAccess(can_push=False, reason="x")
        )

        with patch(
            "cliff.api.routes.agent_execution.get_workspace",
            return_value=_make_workspace(
                repo_url="https://github.com/cliff-security/NodeGoat"
            ),
        ), patch(
            "cliff.api.routes.agent_execution._resolve_repo_env_vars",
            new=AsyncMock(return_value={
                "CLIFF_REPO_URL": "https://github.com/cliff-security/NodeGoat",
            }),
        ), patch(
            "cliff.api.routes.agent_execution.check_repo_push_access",
            new=preflight,
        ):
            resp = await client.post(
                "/api/workspaces/ws-1/agents/remediation_executor/execute"
            )

        assert resp.status_code == 202, resp.text
        assert preflight.await_count == 0


# ---------------------------------------------------------------------------
# URL parser (security): _parse_owner_repo_from_url
# ---------------------------------------------------------------------------
# Direct unit tests for the helper that feeds the preflight. Guards against
# CodeQL py/incomplete-url-substring-sanitization regressions — the parser
# must use an exact hostname match, not a substring/endswith check.


class TestParseOwnerRepoFromUrl:
    def test_canonical_https_url(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url(
            "https://github.com/owner/repo"
        ) == ("owner", "repo")

    def test_strips_trailing_dot_git(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url(
            "https://github.com/owner/repo.git"
        ) == ("owner", "repo")

    def test_extra_path_segments_ignored(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url(
            "https://github.com/owner/repo/pulls/1"
        ) == ("owner", "repo")

    def test_rejects_github_com_in_path(self):
        """Bypass attempt: attacker domain with 'github.com' in the path
        must not be parsed as a GitHub URL."""
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert (
            _parse_owner_repo_from_url(
                "https://attacker.com/github.com/owner/repo"
            )
            is None
        )

    def test_rejects_github_com_as_subdomain_prefix(self):
        """Bypass attempt: 'github.com.attacker.com' would pass a naive
        ``endswith('github.com')`` check but is a different hostname."""
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert (
            _parse_owner_repo_from_url(
                "https://github.com.attacker.com/owner/repo"
            )
            is None
        )

    def test_rejects_subdomain_of_github_com(self):
        """``raw.githubusercontent.com`` and similar must not be accepted —
        the preflight calls the v3 API which only lives at api.github.com /
        github.com proper."""
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert (
            _parse_owner_repo_from_url(
                "https://raw.githubusercontent.com/owner/repo"
            )
            is None
        )

    def test_rejects_non_github_host(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert (
            _parse_owner_repo_from_url("https://gitlab.com/owner/repo")
            is None
        )

    def test_rejects_non_http_scheme(self):
        """``javascript:`` / ``file://`` / SSH URLs should be rejected so
        the preflight never tries to GET them."""
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert (
            _parse_owner_repo_from_url("git@github.com:owner/repo.git")
            is None
        )
        assert (
            _parse_owner_repo_from_url("file:///github.com/owner/repo")
            is None
        )

    def test_rejects_missing_repo_segment(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url("https://github.com/owner") is None
        assert _parse_owner_repo_from_url("https://github.com/") is None

    def test_rejects_empty_and_non_string(self):
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url("") is None
        # Guard against accidental None being passed from a caller that
        # forgot to validate.
        assert _parse_owner_repo_from_url(None) is None  # type: ignore[arg-type]

    def test_hostname_case_insensitive(self):
        """RFC 3986: host is case-insensitive. Don't reject GITHUB.COM."""
        from cliff.api.routes.agent_execution import _parse_owner_repo_from_url

        assert _parse_owner_repo_from_url(
            "https://GitHub.com/owner/repo"
        ) == ("owner", "repo")


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
