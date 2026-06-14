"""Per-agent output schemas for structured output validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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


class EvidenceOutput(BaseModel):
    """Structured output from the Evidence Collector agent.

    Filling the schema gap ADR-0043 §11.1 flagged: pre-migration the
    evidence_collector emitted free-form ``structured_output`` validated
    only by the runtime guard in ``services/evidence_guard.py``. Pydantic
    AI uses this class as ``output_type`` so the parse failure mode is
    "field-shape mismatch", not "no schema at all".
    """

    affected_files: list[dict[str, Any]] = Field(default_factory=list)
    dependency_chain: list[str] = Field(default_factory=list)
    dependency_type: str | None = None
    current_version: str | None = None
    fix_safety: str
    fix_safety_reasoning: str | None = None
    test_coverage: dict[str, Any] = Field(default_factory=dict)
    recommended_approach: str
    impact_assessment: str | None = None

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


# ---------------------------------------------------------------------------
# Triage (ADR-0051 / PRD-0008) — one schema for both producers
# ---------------------------------------------------------------------------

#: The four triage verdicts. ``needs_review`` is the non-terminal low-signal
#: gate (no terminal recommendation); the other three are confirmable.
TriageVerdict = Literal["real", "unexploitable", "false_positive", "needs_review"]

#: The two distinct closes a non-real verdict can recommend.
TriageClose = Literal["false_positive", "unexploitable"]

#: verdict → the only coherent recommended_close (ADR-0051 §2 pairing table).
_VERDICT_TO_CLOSE: dict[str, str | None] = {
    "real": None,
    "needs_review": None,
    "false_positive": "false_positive",
    "unexploitable": "unexploitable",
}


class TriageReachabilityNode(BaseModel):
    """One node in the reachability call-path the panel renders as a chain."""

    label: str
    detail: str | None = None
    kind: str | None = None  # e.g. "entrypoint" | "step" | "sink"

    model_config = {"extra": "allow"}


class TriageReachability(BaseModel):
    """Projected from the exposure analyzer's ``reachable`` /
    ``reachability_evidence`` (ADR-0042). ``reached=False`` with an empty
    ``path`` is the calm "No path found" state (PRD-0008 Story 2)."""

    reached: bool
    path: list[TriageReachabilityNode] = Field(default_factory=list)
    summary: str | None = None

    model_config = {"extra": "allow"}


class TriageExploitability(BaseModel):
    """Whether untrusted input can reach the sink. ``unknown`` routes the
    verdict to ``needs_review`` (ADR-0051 §9)."""

    exploitable: Literal["yes", "no", "unknown"]
    reason: str | None = None

    model_config = {"extra": "allow"}


class TriageClaimVsCode(BaseModel):
    """The report side-by-side: the reporter's cited snippet vs the actual
    repo code (PRD-0008 Story 5)."""

    file: str | None = None
    claimed: str | None = None  # the reporter's snippet / claim
    actual: str | None = None  # the real code at the cited location
    assessment: str | None = None  # one-line judgment

    model_config = {"extra": "allow"}


class TriageReport(BaseModel):
    """Report-only evidence block; ``None`` for scanner findings."""

    claim: str | None = None
    claim_vs_code: TriageClaimVsCode | None = None
    duplicate: bool | None = None
    poc_present: bool | None = None
    ai_slop_signals: list[str] = Field(default_factory=list)
    drafted_reply: str | None = None

    model_config = {"extra": "allow"}


class TriageCheck(BaseModel):
    """A proof row the panel renders. ``kind`` drives the icon/tone
    (pass / warn / fail / info)."""

    eyebrow: str
    result: str
    kind: str
    detail: str | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Deep dive (ADR-0052) — the agentic triage blocks added to TriageOutput.
# Additive: every field defaults, so a pre-deep-dive TriageOutput still loads.
# ---------------------------------------------------------------------------


class ReproRecipe(BaseModel):
    """How V2 would reproduce the exploit. Authored in V1, executed in V2 —
    the frozen sandbox seam (ADR-0052 §3)."""

    setup: list[str] = Field(default_factory=list)
    docker_compose: str | None = None
    image: str | None = None
    ports: list[int] = Field(default_factory=list)
    trigger: list[str] = Field(default_factory=list)
    expected_observation: str | None = None

    model_config = {"extra": "allow"}


class ExploitHypothesis(BaseModel):
    id: str
    trigger_condition: str
    attacker_input: str | None = None
    reached_sink: str | None = None  # file:line
    expected_impact: str | None = None
    impact_class: str | None = None  # RCE | SSRF | SQLi | ...
    repro_recipe: ReproRecipe | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    model_config = {"extra": "allow"}


class ExploitPlan(BaseModel):
    """Ranked exploit hypotheses + repro recipes. ``no_credible_exploit`` is the
    reachable-but-not-exploitable (hardening) signal (ADR-0052 §2)."""

    hypotheses: list[ExploitHypothesis] = Field(default_factory=list)
    primary_hypothesis_id: str | None = None
    no_credible_exploit: bool = False

    model_config = {"extra": "allow"}


class ChallengeReviewer(BaseModel):
    lens: str  # reachability | exploit | impact
    verdict: Literal["holds", "refuted"]
    refutation: str | None = None

    model_config = {"extra": "allow"}


class Challenge(BaseModel):
    """The adversarial disprove panel's verdict (ADR-0052 §2). Resolution is
    deterministic: a majority of ``refuted`` reviewers downgrades the verdict."""

    verdict_holds: bool
    reviewers: list[ChallengeReviewer] = Field(default_factory=list)
    downgraded_verdict: TriageVerdict | None = None
    confidence_adjustment: float = 0.0

    model_config = {"extra": "allow"}


class TriageProvenance(BaseModel):
    """What the Deep dive actually did — transparency + the SHA a verdict is
    valid for (ADR-0052 §2/§6)."""

    steps_run: list[str] = Field(default_factory=list)
    traced_sha: str | None = None
    model_tiers: dict[str, str] = Field(default_factory=dict)  # step -> tier
    exit_stage: str | None = None
    escalated: bool = False

    model_config = {"extra": "allow"}


class TriageOutput(BaseModel):
    """The triage verdict (ADR-0051 §2). Emitted by both the deterministic
    scanner ``triage_synthesizer`` and the LLM ``report_triager``; the
    ``report`` block is populated only for reports.

    The Deep dive (ADR-0052) additionally fills ``exploit_plan`` / ``challenge``
    / ``provenance`` — all optional, so the shipped UI and any pre-deep-dive
    output keep working unchanged.

    ``recommended_close`` is a coherent projection of ``verdict``: it is
    filled from the verdict when omitted and rejected when it contradicts the
    verdict, so the pairing is a HARD invariant (ADR-0051 §2 / eval
    ``pairing_coherent``)."""

    verdict: TriageVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_close: TriageClose | None = None
    reachability: TriageReachability | None = None
    exploitability: TriageExploitability | None = None
    report: TriageReport | None = None
    checks: list[TriageCheck] = Field(default_factory=list)
    # Deep dive (ADR-0052) — additive, all optional.
    exploit_plan: ExploitPlan | None = None
    challenge: Challenge | None = None
    provenance: TriageProvenance | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _coherent_recommended_close(self) -> TriageOutput:
        canonical = _VERDICT_TO_CLOSE[self.verdict]
        if self.recommended_close is None:
            # Fill the canonical projection so V2 never has to re-derive it.
            self.recommended_close = canonical  # type: ignore[assignment]
        elif self.recommended_close != canonical:
            raise ValueError(
                f"recommended_close={self.recommended_close!r} is incoherent with "
                f"verdict={self.verdict!r} (expected {canonical!r})"
            )
        return self


# ---------------------------------------------------------------------------
# Deep dive stage artifacts (ADR-0052 §2) — the per-finding triage trail.
# These persist to the workspace (context/triage/*.json) and feed later stages.
# ---------------------------------------------------------------------------


class RootCauseCandidate(BaseModel):
    file: str
    line: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    why: str | None = None

    model_config = {"extra": "allow"}


class FindingFacts(BaseModel):
    """``gather_facts`` output — the root cause pinned in *this* repo, collected
    once so later stages don't re-locate it (ADR-0052 §2)."""

    vuln_class: str | None = None
    root_cause_candidates: list[RootCauseCandidate] = Field(default_factory=list)
    entry_point_hypothesis: str | None = None
    provided_poc: str | None = None
    claim: str | None = None  # reports: the extracted claim
    static_evidence: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


#: Why a finding was ruled out (ADR-0052 §2 / ADR-0049 FP-class catalog).
KillClass = Literal[
    "root_cause_in_nonship_code",
    "dispatcher_gate",
    "downstream_filter",
    "production_default_off",
    "duplicate_of_known",
    "walk_parallel_guard",
    "walk_catch_frame",
    "not_reachable_by_design",
    "other",
]


class RuleOutResult(BaseModel):
    """``rule_out`` output. ``killed`` short-circuits the pipeline to the
    recommended close (ADR-0052 §2 fail-cheap exit)."""

    killed: bool
    kill_class: KillClass | None = None
    kill_evidence: str | None = None  # file:line / reference
    dedup_match: str | None = None  # prior issue id
    surviving_concerns: list[str] = Field(default_factory=list)
    recommended_verdict_on_kill: TriageClose | None = None

    model_config = {"extra": "allow"}


class ReachNode(BaseModel):
    file: str
    line: int | None = None
    symbol: str | None = None
    role: Literal["source", "hop", "sink"] = "hop"
    note: str | None = None

    model_config = {"extra": "allow"}


class Disproof(BaseModel):
    """The specific reason a finding is unreachable — a guard at file:line, not
    an absence of evidence (ADR-0052 §2: ``unexploitable`` means *this*)."""

    guard_location: str  # file:line
    guard_kind: str | None = None
    explanation: str | None = None

    model_config = {"extra": "allow"}


class DeepReachability(BaseModel):
    """``trace_path`` output — the proven path, or the specific disproof."""

    reached: Literal["yes", "no", "unknown"]
    path: list[ReachNode] = Field(default_factory=list)
    disproof: Disproof | None = None
    trust_boundary_crossed: bool | None = None
    disciplines_applied: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


# Maps agent_type -> the Pydantic model for its structured_output.
AGENT_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "finding_enricher": EnrichmentOutput,
    "owner_resolver": OwnershipOutput,
    "exposure_analyzer": ExposureOutput,
    "evidence_collector": EvidenceOutput,
    "remediation_planner": PlanOutput,
    "remediation_executor": RemediationExecutorOutput,
    "validation_checker": ValidationOutput,
    # ADR-0051 — the report triager emits a TriageOutput. The scanner
    # synthesizer is a pure function (no agent run), so it is not registered
    # here; it constructs + validates TriageOutput directly.
    "report_triager": TriageOutput,
}
