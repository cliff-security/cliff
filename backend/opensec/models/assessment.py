"""Assessment domain model (IMPL-0002 Milestone A; PRD-0003 v0.2 expanded).

An Assessment is one run of the deterministic scan engine against a repo. It
emits a list of Findings plus a set of PostureCheck results. The grade is
derived from ten criteria at read-time; ``criteria_snapshot`` is only written
to persist the values at completion time. Old five-criteria snapshots still
load because the new fields default to ``False``.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 — Pydantic needs this at runtime
from typing import Any, Literal

from pydantic import BaseModel

AssessmentStatus = Literal["pending", "running", "complete", "failed"]
Grade = Literal["A", "B", "C", "D", "F"]


class CriteriaSnapshot(BaseModel):
    """Ten-criteria snapshot persisted at completion time.

    Each grade-counting criterion is a tri-state:

    * ``True`` — verified pass
    * ``False`` — verified fail
    * ``None`` — could not be verified (e.g. a posture check returned
      ``unknown`` because no GitHub token was configured for the daemon)

    Old JSON that stored bare ``False`` still rehydrates cleanly. The
    ``None`` case existed before this change but was silently collapsed
    to ``False`` by ``status == "pass"`` shorthand in :func:`_build_snapshot`,
    making "we couldn't check" indistinguishable from "we checked and it
    failed". Grading still treats unknown as not-met (conservative), but
    consumers can now render a third state instead of a misleading ✗.
    """

    # Carried from PRD-0002.
    no_critical_vulns: bool | None = False
    posture_checks_passing: int = 0
    posture_checks_total: int = 0
    security_md_present: bool | None = False
    dependabot_present: bool | None = False

    # New in PRD-0003 v0.2.
    no_high_vulns: bool | None = False
    branch_protection_enabled: bool | None = False
    no_secrets_detected: bool | None = False
    actions_pinned_to_sha: bool | None = False
    no_stale_collaborators: bool | None = False
    code_owners_exists: bool | None = False
    secret_scanning_enabled: bool | None = False

    def met_count(self) -> int:
        """How many of the 10 grading criteria are verified-pass.

        Only ``True`` counts; ``False`` (verified fail) and ``None``
        (unknown) both contribute zero. This keeps grading conservative —
        unverified does not become a free pass.
        """
        return sum(
            1
            for v in (
                self.no_critical_vulns,
                self.no_high_vulns,
                self.security_md_present,
                self.dependabot_present,
                self.branch_protection_enabled,
                self.no_secrets_detected,
                self.actions_pinned_to_sha,
                self.no_stale_collaborators,
                self.code_owners_exists,
                self.secret_scanning_enabled,
            )
            if v is True
        )

    def all_met(self) -> bool:
        """True when every one of the 10 criteria is satisfied (Grade A gate)."""
        return self.met_count() == 10


ToolState = Literal["pending", "active", "done", "skipped"]
ToolResultKind = Literal["findings_count", "pass_count"]


class AssessmentToolResult(BaseModel):
    kind: ToolResultKind
    value: int
    text: str


class AssessmentTool(BaseModel):
    """Single entry in the ADR-0032 ``tools[]`` payload.

    Replaces the parallel ``scanner_versions`` + ``tool_states[]`` payloads
    from earlier drafts; the architect's regression test
    ``test_dashboard_omits_legacy_scanner_versions`` guards against either of
    those legacy keys leaking back in.
    """

    id: str  # "trivy" | "semgrep" | "posture"
    label: str
    version: str | None = None
    icon: str
    state: ToolState
    result: AssessmentToolResult | None = None


class AssessmentCreate(BaseModel):
    repo_url: str


class AssessmentUpdate(BaseModel):
    status: AssessmentStatus | None = None
    completed_at: datetime | None = None
    grade: Grade | None = None
    criteria_snapshot: CriteriaSnapshot | None = None
    tools: list[AssessmentTool] | None = None


class Assessment(BaseModel):
    id: str
    repo_url: str
    started_at: datetime
    completed_at: datetime | None = None
    status: AssessmentStatus = "pending"
    grade: Grade | None = None
    criteria_snapshot: CriteriaSnapshot | None = None
    tools: list[AssessmentTool] | None = None
    summary_seen_at: datetime | None = None


class AssessmentResult(BaseModel):
    """Ephemeral return shape from the assessment engine (Session A).

    Route handlers in Session B call ``run_assessment(repo_url) -> AssessmentResult``
    and persist the pieces to their respective tables.
    """

    assessment_id: str
    repo_url: str
    grade: Grade
    criteria_snapshot: CriteriaSnapshot
    findings: list[dict[str, Any]] = []
    posture_checks: list[dict[str, Any]] = []
    tools: list[AssessmentTool] = []
