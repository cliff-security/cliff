"""Generic agent adapter for the eval harness (ADR-0050 §1).

One call drives any workspace-scoped runtime agent: build the model, build
the agent, construct ``WorkspaceDeps`` from the case input, render the same
user prompt the executor uses, and run. The model can be injected (a
``FunctionModel`` for the deterministic CI lane) or built from canonical AI
state (the live lane).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cliff.agents.runtime._prompts import build_user_prompt
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.provider import build_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from cliff.evals.registry import AgentEvalSpec


async def run_agent(
    spec: AgentEvalSpec,
    finding: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    model_id: str | None = None,
    model: Model | None = None,
    prior_context: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Run *spec*'s agent over a single eval case and return its output object.

    Provide ``model`` directly (CI lane: a ``FunctionModel``/``TestModel``) or
    ``env`` + ``model_id`` to build a real model (live lane). The returned
    object is the agent's structured ``output_type`` instance (e.g.
    ``EnrichmentOutput``), exactly what evaluators score.
    """
    resolved_model = model if model is not None else build_model(env or {}, model_id)
    agent = spec.build_agent(resolved_model)
    deps = WorkspaceDeps(
        workspace_id="eval",
        workspace_dir="/tmp/cliff-eval",
        finding=finding,
        prior_context=prior_context or {},
        env_vars=env or {},
    )
    result = await agent.run(build_user_prompt(deps), deps=deps)
    return result.output


__all__ = ["run_agent"]
