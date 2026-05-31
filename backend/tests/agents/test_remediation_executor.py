"""Remediation Executor agent — Pydantic AI runtime (ADR-0045, PR2.B).

Drives the agent with Pydantic AI's testing models (no real LLM):

* ``TestModel(call_tools=[])`` — completes immediately, yields a validated
  ``RemediationExecutorOutput``.
* ``FunctionModel`` — calls ``bash`` with a gated command so the tool
  raises ``ApprovalRequired`` and the run pauses, yielding
  ``DeferredToolRequests`` with the pending approval + metadata.
"""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.remediation_executor import SYSTEM_PROMPT, build_agent
from cliff.agents.schemas import RemediationExecutorOutput


@pytest.fixture
def deps(tmp_path) -> WorkspaceDeps:
    return WorkspaceDeps(
        workspace_id="ws-1",
        workspace_dir=str(tmp_path),
        finding={"id": "f-1", "title": "lodash CVE"},
        env_vars={"GH_TOKEN": "ghx"},
    )


def test_system_prompt_preserves_safety_rules():
    # The load-bearing safety guidance (each hard rule = a real shipped
    # regression) must survive the template → SYSTEM_PROMPT lift.
    assert "Workspace safety" in SYSTEM_PROMPT
    assert "Never invent a SHA" in SYSTEM_PROMPT
    assert "needs_approval" in SYSTEM_PROMPT
    assert "Never sweep-upgrade" in SYSTEM_PROMPT


def test_build_agent_registers_five_tools(deps):
    agent = build_agent(TestModel(call_tools=[]))
    # The five in-process tools are registered by name.
    tool_names = set(agent._function_toolset.tools)  # noqa: SLF001 — test introspection
    assert {"bash", "edit", "read", "webfetch", "gh"} <= tool_names


@pytest.mark.asyncio
async def test_normal_completion_yields_structured_output(deps):
    agent = build_agent(TestModel(call_tools=[]))
    result = await agent.run("Execute the plan.", deps=deps)
    assert isinstance(result.output, RemediationExecutorOutput)


@pytest.mark.asyncio
async def test_gated_tool_call_defers_the_run(deps):
    def _call_gated_bash(messages, info):
        # First turn: ask to run a destructive command. The bash tool
        # classifies it as "ask" and raises ApprovalRequired, so the run
        # should pause with a DeferredToolRequests output.
        return ModelResponse(
            parts=[ToolCallPart(tool_name="bash", args={"command": "rm -rf build/"})]
        )

    agent = build_agent(FunctionModel(_call_gated_bash))
    result = await agent.run("Execute the plan.", deps=deps)

    assert isinstance(result.output, DeferredToolRequests)
    assert len(result.output.approvals) == 1
    pending = result.output.approvals[0]
    assert pending.tool_name == "bash"
    # Our gate attaches the human-readable command to the metadata so the
    # frontend can render "approve `rm -rf build/`?".
    meta = result.output.metadata[pending.tool_call_id]
    assert meta["command"] == "rm -rf build/"


@pytest.mark.asyncio
async def test_catastrophic_command_errors_without_deferring(deps):
    """A deny-tier command must NOT become an approval prompt — it errors
    so the model pivots, and the run does not pause for the user."""
    calls = {"n": 0}

    def _model(messages, info):
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="bash", args={"command": "sudo rm -rf /"})]
            )
        # Second turn (after the tool returned its ValueError as a retry):
        # complete with a structured failure.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"status": "failed", "error_details": "blocked"},
                )
            ]
        )

    agent = build_agent(FunctionModel(_model))
    result = await agent.run("Execute the plan.", deps=deps)
    # Did NOT defer — the deny became a tool error the model recovered from.
    assert isinstance(result.output, RemediationExecutorOutput)
    assert result.output.status == "failed"
