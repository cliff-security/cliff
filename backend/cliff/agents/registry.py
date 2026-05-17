"""Agent registry — single source of truth for agent chip metadata.

When adding a new agent to the pipeline, add an entry here. The frontend
fetches this list via GET /api/agents/chips — no frontend changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentChip:
    """UI chip metadata for an agent type."""

    agent_type: str
    label: str   # User-facing label (sentence case)
    icon: str    # Material Symbols icon name
    section: str  # Context section this agent writes to


# Ordered list — this defines the pipeline order shown in the UI.
# owner_resolver excluded from MVP pipeline (IMPL-0001 WP4).
AGENT_CHIPS: list[AgentChip] = [
    AgentChip("finding_enricher", "Enrich finding", "search", "enrichment"),
    AgentChip("exposure_analyzer", "Check exposure", "shield", "exposure"),
    AgentChip("evidence_collector", "Collect evidence", "biotech", "evidence"),
    AgentChip("remediation_planner", "Build remediation plan", "checklist", "plan"),
    AgentChip("remediation_executor", "Remediate", "build", "remediation"),
    AgentChip("validation_checker", "Validate closure", "verified", "validation"),
]
