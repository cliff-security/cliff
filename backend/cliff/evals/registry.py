"""Per-agent eval registry (ADR-0050 §1).

One ``AgentEvalSpec`` per eval target — the single source of truth for what
each agent supports, its budget, and how to build it. The runner validates a
dataset's declared assertions against ``supported_assertions``.

Only ``finding_enricher`` is wired today (ADR-0050 rollout §7: highest-risk
first). Add entries as each agent's eval lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cliff.agents.runtime.finding_enricher import build_agent as _build_enricher
from cliff.agents.schemas import EnrichmentOutput

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel
    from pydantic_ai import Agent
    from pydantic_ai.models import Model


@dataclass(frozen=True)
class BudgetSpec:
    """Budget ceilings, enforced by the runner (ADR-0050 §4). The token + time
    caps are reliable hard limits; ``*_usd`` is best-effort (skipped when the
    model isn't in the pricing table). A breach fails the eval run."""

    # Per case.
    max_usd: float | None = None
    max_tokens: int | None = None
    max_duration_s: float | None = None
    # Per run (whole dataset) — the runaway-bill stop.
    max_run_usd: float | None = None
    max_run_tokens: int | None = None


@dataclass(frozen=True)
class AgentEvalSpec:
    name: str
    build_agent: Callable[[Model], Agent]
    output_type: type[BaseModel]
    abstention_required: bool
    supported_assertions: frozenset[str]
    budget: BudgetSpec
    default_model: str | None = None
    live_only: bool = False
    eval_frozen: bool = False  # deprecated agents (owner_resolver): keep, don't maintain


_REGISTRY: dict[str, AgentEvalSpec] = {
    "finding_enricher": AgentEvalSpec(
        name="finding_enricher",
        build_agent=_build_enricher,
        output_type=EnrichmentOutput,
        abstention_required=True,
        supported_assertions=frozenset(
            {
                "citation_liveness",
                "cve_ids",
                "cvss_within",
                "no_jargon_title",
                "abstention",
            }
        ),
        budget=BudgetSpec(
            max_usd=0.03,
            max_tokens=8000,
            max_duration_s=60.0,
            max_run_usd=0.50,
            max_run_tokens=120_000,
        ),
    ),
}


def get_spec(name: str) -> AgentEvalSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No eval spec for {name!r}. Registered: {sorted(_REGISTRY)}"
        ) from None


def all_specs() -> list[AgentEvalSpec]:
    return list(_REGISTRY.values())


__all__ = ["AgentEvalSpec", "BudgetSpec", "all_specs", "get_spec"]
