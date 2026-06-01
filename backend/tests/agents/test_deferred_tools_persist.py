"""DeferredToolRequests park + resume lifecycle (ADR-0047 / IMPL-0022 PR2.C).

Exercises the REAL mechanism end-to-end with a ``FunctionModel`` (no live
LLM): the remediation_executor calls a gated tool (``rm -rf build/``), the
bash tool raises ``ApprovalRequired``, the run pauses with a
``DeferredToolRequests`` output, and the executor persists the marker +
message history. Then ``resume_executor`` continues the run with the
user's ``ToolApproved`` / ``ToolDenied`` decision and finalizes it.

The agent_run row is backed by a small in-test stateful fake (patched repo
functions) so the marker lifecycle is asserted without a full DB + FK
setup; the message-history JSON that flows park→resume is the REAL
``all_messages_json()`` output, so the resume deserialization path is
genuinely covered.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from cliff.agents.executor import AgentExecutor
from cliff.models import AgentRun, AgentRunUpdate

_FINDING = {
    "id": "f-1",
    "title": "lodash prototype pollution",
    "source_type": "trivy",
    "source_id": "CVE-2020-8203",
    "description": "lodash < 4.17.19 prototype pollution.",
    "status": "in_progress",
}


@pytest.fixture
def workspace_dir(tmp_path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "finding.json").write_text(json.dumps(_FINDING))
    return str(tmp_path)


def _gated_then_complete_model() -> FunctionModel:
    """FunctionModel: first turn calls gated bash; once that bash call is in
    the history (i.e. on resume), completes with a structured result."""

    def _fn(messages, info):
        already_called_bash = any(
            isinstance(part, ToolCallPart) and part.tool_name == "bash"
            for msg in messages
            if isinstance(msg, ModelResponse)
            for part in msg.parts
        )
        if already_called_bash:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="final_result",
                        args={
                            "status": "changes_made",
                            "changes_summary": "removed stale build dir",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[ToolCallPart(tool_name="bash", args={"command": "rm -rf build/"})]
        )

    return FunctionModel(_fn)


class _FakeRunStore:
    """In-test stand-in for the agent_run row the executor reads/writes."""

    def __init__(self):
        self.state: dict = {
            "status": "running",
            "permission_pending": False,
            "permission_request": None,
            "pa_message_history": None,
        }
        self.update_calls: list[AgentRunUpdate] = []

    def run(self) -> AgentRun:
        return AgentRun(
            id="run-x",
            workspace_id="ws-1",
            agent_type="remediation_executor",
            status=self.state["status"],
            permission_pending=self.state["permission_pending"],
            permission_request=self.state["permission_request"],
        )

    async def create(self, *_a, **_k) -> AgentRun:
        return self.run()

    async def update(self, _db, _run_id, upd: AgentRunUpdate):
        self.update_calls.append(upd)
        for field, value in upd.model_dump(exclude_unset=True).items():
            self.state[field] = value
        return self.run()

    async def get(self, _db, _run_id) -> AgentRun:
        return self.run()

    async def get_history(self, _db, _run_id):
        return self.state["pa_message_history"]


def _build_executor(store: _FakeRunStore) -> AgentExecutor:
    builder = AsyncMock()
    builder.update_context.return_value = 1
    builder._mcp_resolver = None  # no MCP toolsets in the test
    ex = AgentExecutor(
        AsyncMock(),
        builder,
        ai_env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "x"}),
        ai_model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
    )
    # Both the initial run and the resume build their agent off this model.
    model = _gated_then_complete_model()
    ex._resolve_active_model = AsyncMock(return_value=model)
    return ex


@pytest.mark.asyncio
async def test_gated_tool_parks_marker_then_resume_completes(workspace_dir):
    store = _FakeRunStore()
    executor = _build_executor(store)

    patches = (
        patch("cliff.agents.executor.create_agent_run", store.create),
        patch("cliff.agents.executor.update_agent_run", store.update),
        patch("cliff.agents.executor.get_agent_run", store.get),
        patch("cliff.agents.executor.get_pa_message_history", store.get_history),
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
    )
    for p in patches:
        p.start()
    try:
        # --- Initial run: gated bash → pause ---
        result = await executor.execute(
            "ws-1", "remediation_executor", AsyncMock(),
            workspace_dir=workspace_dir,
            env_vars={"GH_TOKEN": "ghx"},
        )

        assert result.status == "awaiting_permission"
        # Marker persisted, frontend-renderable shape + resume ids.
        assert store.state["permission_pending"] is True
        marker = store.state["permission_request"]
        assert marker["tool"] == "bash"
        assert marker["patterns"] == ["rm -rf build/"]
        assert len(marker["tool_call_ids"]) == 1
        # Message history persisted for resume (real PA serialization).
        assert store.state["pa_message_history"]
        assert "rm -rf build/" in store.state["pa_message_history"]

        # --- Resume with approval: run continues to completion ---
        resume_result = await executor.resume_executor(
            AsyncMock(), "ws-1", "run-x",
            approved=True,
            workspace_dir=workspace_dir,
            env_vars={"GH_TOKEN": "ghx"},
        )

        assert resume_result.status == "completed"
        assert resume_result.parse_result.structured_output["status"] == "changes_made"
        # Marker cleared on resume (idempotency + no stale awaiting_permission).
        assert store.state["permission_pending"] is False
        assert store.state["permission_request"] is None
        assert store.state["pa_message_history"] is None
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_resume_without_pending_marker_raises(workspace_dir):
    """Resuming a run that isn't paused is a 4xx-worthy error, not a crash."""
    from cliff.agents.errors import AgentProcessError

    store = _FakeRunStore()  # permission_pending stays False
    executor = _build_executor(store)

    with (
        patch("cliff.agents.executor.get_agent_run", store.get),
        patch("cliff.agents.executor.get_pa_message_history", store.get_history),
        pytest.raises(AgentProcessError, match="No pending permission request"),
    ):
        await executor.resume_executor(
            AsyncMock(), "ws-1", "run-x",
            approved=True, workspace_dir=workspace_dir,
        )


@pytest.mark.asyncio
async def test_resume_with_corrupt_history_marks_failed_not_wedged(workspace_dir):
    """A corrupt pa_message_history must mark the run failed (recoverable),
    never leave it wedged at running + permission_pending forever."""
    store = _FakeRunStore()
    store.state.update(
        {
            "permission_pending": True,
            "permission_request": {
                "tool": "bash",
                "patterns": ["rm -rf x"],
                "tool_call_ids": ["call-1"],
            },
            "pa_message_history": "{ this is not valid pydantic-ai json",
        }
    )
    executor = _build_executor(store)

    patches = (
        patch("cliff.agents.executor.get_agent_run", store.get),
        patch("cliff.agents.executor.update_agent_run", store.update),
        patch("cliff.agents.executor.get_pa_message_history", store.get_history),
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
    )
    for p in patches:
        p.start()
    try:
        result = await executor.resume_executor(
            AsyncMock(), "ws-1", "run-x",
            approved=True, workspace_dir=workspace_dir,
        )
        # Failed, not raised; marker cleared so the workspace isn't wedged.
        assert result.status == "failed"
        assert store.state["status"] == "failed"
        assert store.state["permission_pending"] is False
    finally:
        for p in patches:
            p.stop()
