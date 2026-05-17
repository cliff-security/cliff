"""Per-agent output schemas for structured output validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common output wrapper (matches ADR-0008 output contract)
# ---------------------------------------------------------------------------


class AgentOutput(BaseModel):
    """Common output contract that every sub-agent must return."""

    summary: str
    result_card_markdown: str = ""
    structured_output: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_sources: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None


# ---------------------------------------------------------------------------
# Per-agent structured_output schemas (validate required fields only)
# ---------------------------------------------------------------------------


class EnrichmentOutput(BaseModel):
    """Structured output from the Finding Enricher agent."""

    normalized_title: str
    cve_ids: list[str] = Field(default_factory=list)
    cvss_score: float | None = Field(default=None, ge=0.0, le=10.0)
    cvss_vector: str | None = None
    description: str | None = None
    affected_versions: str | None = None
    fixed_version: str | None = None
    known_exploits: bool = False
    exploit_details: str | None = None
    references: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class OwnershipOutput(BaseModel):
    """Structured output from the Owner Resolver agent."""

    recommended_owner: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str | None = None

    model_config = {"extra": "allow"}


class ExposureOutput(BaseModel):
    """Structured output from the Exposure/Context Analyzer agent."""

    recommended_urgency: str
    environment: str | None = None
    internet_facing: bool | None = None
    reachable: str | None = None
    reachability_evidence: str | None = None
    business_criticality: str | None = None
    blast_radius: str | None = None

    model_config = {"extra": "allow"}


class PlanOutput(BaseModel):
    """Structured output from the Remediation Planner agent."""

    plan_steps: list[str]
    definition_of_done: list[str] = Field(default_factory=list)
    interim_mitigation: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    estimated_effort: str | None = None
    suggested_due_date: str | None = None
    validation_method: str | None = None

    model_config = {"extra": "allow"}


class ValidationOutput(BaseModel):
    """Structured output from the Validation Checker agent."""

    verdict: str
    recommendation: str
    evidence: str | None = None
    remaining_concerns: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class RemediationExecutorOutput(BaseModel):
    """Structured output from the Remediation Executor agent."""

    status: str
    pr_url: str | None = None
    branch_name: str | None = None
    changes_summary: str | None = None
    test_results: str | None = None
    error_details: str | None = None

    model_config = {"extra": "allow"}


# Maps agent_type -> the Pydantic model for its structured_output.
AGENT_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "finding_enricher": EnrichmentOutput,
    "owner_resolver": OwnershipOutput,
    "exposure_analyzer": ExposureOutput,
    "remediation_planner": PlanOutput,
    "remediation_executor": RemediationExecutorOutput,
    "validation_checker": ValidationOutput,
}
