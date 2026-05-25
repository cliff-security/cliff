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

# Machine codes for the failure-detail block (migration 015). The frontend
# renders a static friendly headline + step label per kind; details surface
# the captured stderr/exception.
AssessmentErrorKind = Literal[
    "clone_failed",
    "scanner_failed",
    "timeout",
    "internal_error",
    "interrupted",
]

# Step the engine was executing at the moment of failure. ``clone`` is
# emitted by the runner when ``RepoCloner.clone`` raises (the engine itself
# only emits ``detect`` before the clone returns); the rest mirror the v0.2
# step keys in ``api/routes/assessment.py``.
AssessmentFailedStep = Literal[
    "clone",
    "detect",
    "trivy_vuln",
    "trivy_secret",
    "semgrep",
    "posture",
    "descriptions",
    "persist",
    "unknown",
]


class AssessmentError(BaseModel):
    """Failure-detail block surfaced on the assessment status response.

    Populated only when ``status == 'failed'``. The four fields are also
    persisted on the assessment row (migration 015) so a failure outlives
    the in-memory background state and survives a process restart.
    """

    kind: AssessmentErrorKind
    message: str
    failed_step: AssessmentFailedStep | None = None
    details: str | None = None


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
#: Machine-readable reason a tool ended in ``state="skipped"`` (B07). Lets the
#: dashboard distinguish "ran clean, 0 findings" from "never produced results".
ToolError = Literal["timeout", "binary_missing", "exec_failed"]


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

    IMPL-0009 added ``duration_ms``, ``scope``, and ``ran`` for the new
    "Last assessment" dashboard panel. All three are optional — pending
    tools and legacy rows still validate cleanly.
    """

    id: str  # "trivy" | "semgrep" | "posture"
    label: str
    version: str | None = None
    icon: str
    state: ToolState
    result: AssessmentToolResult | None = None
    duration_ms: int | None = None
    scope: str | None = None
    ran: str | None = None
    #: Why a ``state="skipped"`` tool produced no results (B07). ``None`` for
    #: every other state. The dashboard renders a distinct row for this so a
    #: skipped scanner never reads as a successful "0 findings" run.
    error: ToolError | None = None


class AssessmentCreate(BaseModel):
    repo_url: str


class AssessmentUpdate(BaseModel):
    status: AssessmentStatus | None = None
    completed_at: datetime | None = None
    grade: Grade | None = None
    criteria_snapshot: CriteriaSnapshot | None = None
    tools: list[AssessmentTool] | None = None
    # IMPL-0009 — scope captured during the run, persisted at completion.
    commit_sha: str | None = None
    branch: str | None = None
    scanned_files: int | None = None
    scanned_deps: int | None = None
    # Migration 015 — failure detail. Set together when the background
    # runner catches an exception or the watchdog reaps a stale row.
    error_kind: AssessmentErrorKind | None = None
    error_message: str | None = None
    error_details: str | None = None
    failed_step: AssessmentFailedStep | None = None


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
    # IMPL-0009 — scope of this assessment run.
    commit_sha: str | None = None
    branch: str | None = None
    scanned_files: int | None = None
    scanned_deps: int | None = None
    # Migration 015 — populated only when ``status == 'failed'``.
    error_kind: AssessmentErrorKind | None = None
    error_message: str | None = None
    error_details: str | None = None
    failed_step: AssessmentFailedStep | None = None


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
    # IMPL-0009 — scope of this run, mirrored onto the persisted Assessment row.
    commit_sha: str | None = None
    branch: str | None = None
    scanned_files: int | None = None
    scanned_deps: int | None = None
