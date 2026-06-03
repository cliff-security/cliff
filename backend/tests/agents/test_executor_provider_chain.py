"""End-to-end provider chain — canonical state X reaches the agent as Model X.

Locks down the two seams the per-provider factory tests
(``test_runtime_provider.py``) and the per-agent runtime tests
(``test_runtime_no_tools.py``) leave un-handshaken:

1. The ``Model`` returned by ``build_model`` is the one
   ``run_no_tools_agent`` actually receives — not a separately-constructed
   ``TestModel`` like the runtime tests use.
2. Each of the six advertised providers (openrouter / anthropic / openai /
   google / ollama / custom) survives the resolver → factory → agent chain
   with the right subclass + model name on the wire.

Uses the *real* ``build_model`` factory so a regression in any provider
branch (e.g. the gpt-5 ``max_tokens`` probe bug, but for the actual run
path) fails this test for that provider specifically.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cliff.agents.executor import AgentExecutor
from cliff.agents.runtime.deps import WorkspaceDeps

_PROVIDER_CASES = [
    pytest.param(
        {"OPENROUTER_API_KEY": "sk-or-fake"},
        "openrouter/anthropic/claude-haiku-4.5",
        "OpenAIChatModel",
        "anthropic/claude-haiku-4.5",
        id="openrouter",
    ),
    pytest.param(
        {"ANTHROPIC_API_KEY": "sk-ant-fake"},
        "anthropic/claude-haiku-4-5",
        "AnthropicModel",
        "claude-haiku-4-5",
        id="anthropic",
    ),
    pytest.param(
        {"OPENAI_API_KEY": "sk-openai-fake"},
        "openai/gpt-4o-mini",
        "OpenAIChatModel",
        "gpt-4o-mini",
        id="openai",
    ),
    pytest.param(
        {"GEMINI_API_KEY": "AIza-fake"},
        "google/gemini-2.5-flash",
        "GoogleModel",
        "gemini-2.5-flash",
        id="google",
    ),
    pytest.param(
        {},
        "ollama/llama3.1",
        "OpenAIChatModel",
        "llama3.1",
        id="ollama",
    ),
    pytest.param(
        {
            "OPENAI_API_KEY": "sk-custom-fake",
            "OPENAI_BASE_URL": "https://proxy.example/v1",
        },
        "custom/my-model",
        "OpenAIChatModel",
        "my-model",
        id="custom",
    ),
]


@pytest.mark.parametrize(
    "env,model_full_id,expected_class_name,expected_model_name",
    _PROVIDER_CASES,
)
@pytest.mark.asyncio
async def test_provider_chain_reaches_agent_with_correct_model(
    env: dict[str, str],
    model_full_id: str,
    expected_class_name: str,
    expected_model_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    async def _capture_run(agent_type: str, deps: WorkspaceDeps, model: Any) -> dict:
        captured.append(model)
        return {"normalized_title": "ok", "cve_ids": []}

    monkeypatch.setattr(
        "cliff.agents.executor.run_no_tools_agent", _capture_run,
    )

    executor = AgentExecutor(
        context_builder=MagicMock(),
        ai_env_resolver=AsyncMock(return_value=env),
        ai_model_resolver=AsyncMock(return_value=model_full_id),
    )
    deps = WorkspaceDeps(
        workspace_id="ws-1",
        workspace_dir="/tmp/ws",
        finding={"id": "f-1"},
    )

    await executor._run_pa_no_tools("finding_enricher", deps, timeout=30.0)

    assert len(captured) == 1, (
        "run_no_tools_agent was not called exactly once — "
        "the resolver→build_model→agent chain is broken."
    )
    model = captured[0]
    assert type(model).__name__ == expected_class_name, (
        f"Expected {expected_class_name} for provider in "
        f"{model_full_id!r}, got {type(model).__name__}."
    )
    assert model.model_name == expected_model_name, (
        f"Expected model_name={expected_model_name!r} on the wire, "
        f"got {model.model_name!r}."
    )
