"""Generic agent adapter for the eval harness (ADR-0050 §1).

One call drives any workspace-scoped runtime agent: build the model, build
the agent, construct ``WorkspaceDeps`` from the case input, render the same
user prompt the executor uses, and run. The model can be injected (a
``FunctionModel`` for the deterministic CI lane) or built from canonical AI
state (the live lane).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cliff.agents.runtime._prompts import build_user_prompt
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.provider import build_model

if TYPE_CHECKING:
    from pydantic import BaseModel
    from pydantic_ai.models import Model

    from cliff.evals.registry import AgentEvalSpec

# A finding is a raw scanner dict (string keys); values are heterogeneous.
Finding = dict[str, object]


@dataclass
class MeasuredRun:
    """A measured single run — the output plus what it cost (ADR-0050 §4)."""

    output: BaseModel
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_s: float


async def _run(
    spec: AgentEvalSpec,
    finding: Finding,
    *,
    env: dict[str, str] | None,
    model_id: str | None,
    model: Model | None,
    prior_context: dict[str, dict[str, object]] | None,
):
    # CI lane injects ``model``; live lane builds from env + the case/spec model
    # (falling back to the spec's ``default_model`` when no id is supplied).
    resolved_model = (
        model
        if model is not None
        else build_model(env or {}, model_id or spec.default_model)
    )
    agent = spec.build_agent(resolved_model)
    deps = WorkspaceDeps(
        workspace_id="eval",
        workspace_dir="/tmp/cliff-eval",
        finding=dict(finding),
        prior_context=prior_context or {},
        env_vars=env or {},
    )
    return await agent.run(build_user_prompt(deps), deps=deps)


def _validated_output(spec: AgentEvalSpec, result) -> BaseModel:
    """PA already validates against the agent's ``output_type``; assert it so a
    misconfigured registry entry fails loudly rather than scoring garbage."""
    output = result.output
    if not isinstance(output, spec.output_type):
        raise TypeError(
            f"{spec.name}: expected {spec.output_type.__name__}, got "
            f"{type(output).__name__}"
        )
    return output


async def run_agent(
    spec: AgentEvalSpec,
    finding: Finding,
    *,
    env: dict[str, str] | None = None,
    model_id: str | None = None,
    model: Model | None = None,
    prior_context: dict[str, dict[str, object]] | None = None,
) -> BaseModel:
    """Run *spec*'s agent over a single eval case and return its output object.

    Provide ``model`` directly (CI lane: a ``FunctionModel``/``TestModel``) or
    ``env`` + ``model_id`` to build a real model (live lane). The returned
    object is the agent's structured ``output_type`` instance (e.g.
    ``EnrichmentOutput``), exactly what evaluators score.
    """
    result = await _run(
        spec, finding, env=env, model_id=model_id, model=model, prior_context=prior_context
    )
    return _validated_output(spec, result)


async def run_agent_measured(
    spec: AgentEvalSpec,
    finding: Finding,
    *,
    env: dict[str, str] | None = None,
    model_id: str | None = None,
    model: Model | None = None,
    prior_context: dict[str, dict[str, object]] | None = None,
) -> MeasuredRun:
    """Like :func:`run_agent`, but also returns token usage + wall-clock time so
    the runner can enforce a per-case / per-run budget."""
    start = time.monotonic()
    result = await _run(
        spec, finding, env=env, model_id=model_id, model=model, prior_context=prior_context
    )
    duration = time.monotonic() - start
    usage = result.usage
    return MeasuredRun(
        output=_validated_output(spec, result),
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        total_tokens=usage.total_tokens or 0,
        duration_s=duration,
    )


__all__ = ["MeasuredRun", "run_agent", "run_agent_measured"]
