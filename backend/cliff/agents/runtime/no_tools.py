"""Drive a no-tools Pydantic AI agent end-to-end.

Owns the seam between :class:`cliff.agents.executor.AgentExecutor` and
Pydantic AI: pick the right per-agent runtime module, run it against the
canonical ``Model`` built from Cliff's AI state, dump the validated
output to a plain dict so the existing persistence path
(``WorkspaceContextBuilder.update_context`` + ``map_and_upsert``) stays
unchanged.

The post-parse safeguards (``reference_verifier`` for the enricher,
``evidence_guard`` for the evidence collector) are NOT called here —
they live in ``executor.py`` so they can mutate the ``ParseResult`` the
same way they do today. Keeping them at the executor layer means the
exact set of mutations + their log lines stays one diff away from the
OpenCode-era behaviour during the beta friction window.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cliff.agents.runtime._prompts import build_user_prompt
from cliff.agents.runtime.evidence_collector import build_agent as _build_evidence_collector
from cliff.agents.runtime.exposure_analyzer import build_agent as _build_exposure_analyzer
from cliff.agents.runtime.finding_enricher import build_agent as _build_finding_enricher
from cliff.agents.runtime.owner_resolver import build_agent as _build_owner_resolver
from cliff.agents.runtime.remediation_planner import build_agent as _build_remediation_planner
from cliff.agents.runtime.validation_checker import build_agent as _build_validation_checker

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from cliff.agents.runtime.deps import WorkspaceDeps

# Each builder takes a Pydantic AI ``Model`` and returns an ``Agent``
# whose ``output_type`` is the per-agent schema. The output schemas
# differ per agent, so the registry's value type is the widest correct
# shape — ``Agent[WorkspaceDeps, Any]`` — rather than ``Any``.
BuilderFn = Callable[["Model"], "Agent[WorkspaceDeps, Any]"]

# A summariser reads the per-agent ``structured_output`` dict and
# returns either a one-line summary or ``None`` to fall back to the
# generic per-agent label.
SummarizerFn = Callable[[dict[str, Any]], "str | None"]


# Six no-tools agent types and the runtime builder that owns each. The
# remediation_executor stays on the OpenCode tool-use path through
# PR #1 — PR #2 migrates it.
_RUNTIME_BUILDERS: dict[str, BuilderFn] = {
    "finding_enricher": _build_finding_enricher,
    "owner_resolver": _build_owner_resolver,
    "exposure_analyzer": _build_exposure_analyzer,
    "evidence_collector": _build_evidence_collector,
    "remediation_planner": _build_remediation_planner,
    "validation_checker": _build_validation_checker,
}


NO_TOOLS_AGENT_TYPES: frozenset[str] = frozenset(_RUNTIME_BUILDERS.keys())


def is_no_tools_agent(agent_type: str) -> bool:
    """Return True if *agent_type* runs through the in-process PA substrate."""
    return agent_type in _RUNTIME_BUILDERS


async def run_no_tools_agent(
    agent_type: str,
    deps: WorkspaceDeps,
    model: Model,
) -> dict[str, Any]:
    """Run *agent_type* against *model* and return its structured output.

    The returned dict is the ``model_dump()`` of the per-agent Pydantic
    output class — exactly the shape the pre-migration parser produced
    in ``parse_result.structured_output``, so the downstream context +
    sidebar persistence paths see no change in payload shape.

    Raises whatever Pydantic AI raises (``UserError``, ``ModelHTTPError``,
    ``ValidationError``…); :mod:`cliff.agents.executor` is the one place
    that translates those into Cliff's existing ``AgentProcessError`` /
    ``AgentRateLimitError`` taxonomy.
    """
    builder = _RUNTIME_BUILDERS[agent_type]
    agent = builder(model)
    user_prompt = build_user_prompt(deps)
    result = await agent.run(user_prompt, deps=deps)
    return result.output.model_dump()


def _summarize_enricher(o: dict[str, Any]) -> str | None:
    title = o.get("normalized_title")
    cves = o.get("cve_ids") or []
    if title and cves:
        return f"{title} ({', '.join(cves)})."
    return f"{title}." if title else None


def _summarize_planner(o: dict[str, Any]) -> str | None:
    steps = o.get("plan_steps") or []
    suffix = "s" if len(steps) != 1 else ""
    return f"Plan ready ({len(steps)} step{suffix})."


# (agent_type) -> (summary_fn, fallback). The summary_fn returns either a
# rendered one-liner or ``None`` to fall back to the generic label.
_AGENT_SUMMARIES: dict[str, tuple[SummarizerFn, str]] = {
    "finding_enricher": (_summarize_enricher, "Enrichment ready."),
    "owner_resolver": (
        lambda o: f"Recommended owner: {o['recommended_owner']}."
        if o.get("recommended_owner")
        else None,
        "Owner resolved.",
    ),
    "exposure_analyzer": (
        lambda o: f"Recommended urgency: {o['recommended_urgency']}."
        if o.get("recommended_urgency")
        else None,
        "Exposure assessed.",
    ),
    "evidence_collector": (
        lambda o: f"Fix safety: {o['fix_safety']}."
        if o.get("fix_safety")
        else None,
        "Evidence collected.",
    ),
    "remediation_planner": (_summarize_planner, "Remediation plan ready."),
    "validation_checker": (
        lambda o: f"Validation verdict: {o['verdict']}."
        if o.get("verdict")
        else None,
        "Validation complete.",
    ),
}


def derive_summary(
    agent_type: str, structured_output: dict[str, Any]
) -> str:
    """Return a one-line summary for ``agent_run.summary_markdown``.

    Pre-migration the model emitted a dedicated ``summary`` field in
    the JSON wrapper; with ``output_type=<per-agent schema>`` that
    wrapper goes away. Synthesise a short line from a salient field
    per agent so the agent-history row stays informative; fall back
    to a generic label when the salient field is missing.
    """
    summarizer, fallback = _AGENT_SUMMARIES.get(
        agent_type, (lambda _o: None, "Agent completed.")
    )
    return summarizer(structured_output) or fallback


__all__ = [
    "NO_TOOLS_AGENT_TYPES",
    "derive_summary",
    "is_no_tools_agent",
    "run_no_tools_agent",
]
