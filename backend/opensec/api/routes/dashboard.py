"""Dashboard routes (PRD-0003 v0.2 / ADR-0032 / ADR-0027).

Read-only aggregation over the latest assessment, the posture sweep, finding
priority counts, and (if any) completion row. The wire shape exposes the v0.2
contract: a single ``tools[]`` payload, a four-state posture vocabulary
(``pass | fail | done | advisory``) with per-category progress that excludes
advisory rows, the labeled ``criteria[]`` list, vulnerability counts split by
type, and the ``summary_seen_at`` flag that gates the assessment-complete
interstitial.

Phase 2 of IMPL-0003-p2 swaps every posture query from the legacy
``posture_check`` DAO to the unified ``finding`` table (ADR-0027). The
four-state projection now reads ``(status, pr_url, grade_impact)`` from the
posture finding row.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from opensec.assessment.posture import (
    ADVISORY_CHECKS,
    CHECK_CATEGORY,
    CHECK_DISPLAY_NAME,
)
from opensec.db.connection import get_db
from opensec.db.dao.assessment import get_latest_assessment
from opensec.db.dao.completion import get_completion_for_assessment
from opensec.db.dao.dashboard_metrics import assemble_phase2_metrics
from opensec.db.repo_finding import (
    count_findings_by_priority,
    list_findings,
    list_posture_findings,
)
from opensec.models import (
    Assessment,
    AssessmentTool,
    AssessmentToolResult,
    CriteriaSnapshot,
    Finding,
    Grade,
    PostureCheckCategory,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


PostureWireState = Literal["pass", "fail", "done", "advisory"]


# --------------------------------------------------------------------- payload
class CriterionLabel(BaseModel):
    """One row of the labeled ``criteria[]`` list (ADR-0032 §1.4)."""

    key: str
    label: str
    met: bool


class PostureCheckWire(BaseModel):
    name: str
    display_name: str
    category: PostureCheckCategory
    state: PostureWireState
    grade_impact: Literal["counts", "advisory"]
    fixable_by: str | None = None
    detail: str | None = None
    pr_url: str | None = None


class CategoryProgress(BaseModel):
    done: int
    total: int


class PostureCategoryWire(BaseModel):
    name: PostureCheckCategory
    display_name: str
    progress: CategoryProgress
    checks: list[PostureCheckWire]


class PostureWire(BaseModel):
    pass_count: int
    total_count: int
    advisory_count: int
    categories: list[PostureCategoryWire]


class VulnerabilityCounts(BaseModel):
    total: int
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    tool_credits: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------- Phase 2
# PRD-0006 / IMPL-0007 PR-B / B5 — additive trend / needs-you / history fields.
# All series are oldest-first, today is the last element. Series shorter than
# the requested window pad with leading zeros (or ``None`` for grade_history).


class OpenIssuesSeries(BaseModel):
    current: int = 0
    history: list[int] = Field(default_factory=list)
    delta_pct_30d: int = 0


class TimeToCloseSeries(BaseModel):
    current_seconds: int | None = None
    history: list[int | None] = Field(default_factory=list)
    delta_pct_30d: int = 0


class NeedsYouCounts(BaseModel):
    plans_waiting: int = 0
    prs_ready: int = 0
    critical_todo: int = 0


class GradeHistoryPoint(BaseModel):
    date: str
    grade: Literal["A", "B", "C", "D", "F"] | None = None


class SeverityHistory(BaseModel):
    critical: list[int] = Field(default_factory=list)
    high: list[int] = Field(default_factory=list)
    medium: list[int] = Field(default_factory=list)
    low: list[int] = Field(default_factory=list)


class DashboardPayload(BaseModel):
    """v0.2 dashboard wire shape — see ADR-0032 for the full design rationale.

    PRD-0006 Phase 2 (IMPL-0007 PR-B) adds the trend / needs-you / history
    fields below. They are additive and never alter the v0.2 contract; the
    snapshot test in ``test_openapi_snapshot.py`` is the regression guard.
    """

    assessment: Assessment | None
    grade: Grade | None
    criteria: list[CriterionLabel]
    criteria_snapshot: CriteriaSnapshot
    findings_count_by_priority: dict[str, int]
    posture_pass_count: int
    posture_total_count: int
    posture_checks: list[Finding] = []
    posture: PostureWire | None = None
    tools: list[AssessmentTool] = Field(default_factory=list)
    vulnerabilities: VulnerabilityCounts | None = None
    completion_id: str | None = None

    # PRD-0006 Phase 2 additions.
    open_issues: OpenIssuesSeries = Field(default_factory=OpenIssuesSeries)
    time_to_close: TimeToCloseSeries = Field(default_factory=TimeToCloseSeries)
    needs_you: NeedsYouCounts = Field(default_factory=NeedsYouCounts)
    grade_history: list[GradeHistoryPoint] = Field(default_factory=list)
    severity_history: SeverityHistory = Field(default_factory=SeverityHistory)


# ------------------------------------------------------------------- helpers
_CATEGORY_DISPLAY: dict[PostureCheckCategory, str] = {
    "repo_configuration": "Repo configuration",
    "code_integrity": "Code integrity",
    "ci_supply_chain": "CI supply chain",
    "collaborator_hygiene": "Collaborator hygiene",
}

_CRITERIA_ORDER: list[tuple[str, str, str]] = [
    ("security_md_present", "SECURITY.md present", "security_md_present"),
    ("dependabot_configured", "Dependabot configured", "dependabot_present"),
    ("no_critical_vulns", "No critical vulns", "no_critical_vulns"),
    ("no_high_vulns", "No high vulns", "no_high_vulns"),
    ("branch_protection_enabled", "Branch protection enabled", "branch_protection_enabled"),
    ("no_secrets_detected", "No committed secrets", "no_secrets_detected"),
    ("actions_pinned_to_sha", "CI actions pinned to SHA", "actions_pinned_to_sha"),
    ("no_stale_collaborators", "No stale collaborators", "no_stale_collaborators"),
    ("code_owners_exists", "Code owners file exists", "code_owners_exists"),
    ("secret_scanning_enabled", "Secret scanning enabled", "secret_scanning_enabled"),
]


def _criteria_to_labeled(snapshot: CriteriaSnapshot) -> list[CriterionLabel]:
    snap = snapshot.model_dump()
    return [
        CriterionLabel(key=key, label=label, met=bool(snap.get(field)))
        for key, label, field in _CRITERIA_ORDER
    ]


def _check_name_for(finding: Finding) -> str:
    """Extract the posture check name from a ``type='posture'`` finding."""
    payload = finding.raw_payload or {}
    name = payload.get("check_name") if isinstance(payload, dict) else None
    if isinstance(name, str) and name:
        return name
    # Fallback: the title is the check_name when the mapper writes it.
    return finding.title


def _project_posture_state(finding: Finding) -> tuple[PostureWireState, str | None]:
    """Apply ADR-0032 §1.2 four-state projection to a unified posture row.

    * ``status='passed'`` + ``pr_url`` not null → ``done``
    * ``status='passed'`` + ``pr_url`` null    → ``pass``
    * ``grade_impact='advisory'``               → ``advisory``
    * everything else                           → ``fail`` (the row is still
      actionable; agent-submitted PRs without a confirmed pass land here too)
    """
    if finding.grade_impact == "advisory":
        return "advisory", finding.pr_url
    if finding.status == "passed" and finding.pr_url:
        return "done", finding.pr_url
    if finding.status == "passed":
        return "pass", None
    return "fail", finding.pr_url


def _grade_impact_for(check_name: str) -> Literal["counts", "advisory"]:
    return "advisory" if check_name in ADVISORY_CHECKS else "counts"


def _build_posture_payload(checks: list[Finding]) -> PostureWire:
    by_category: dict[PostureCheckCategory, list[PostureCheckWire]] = {
        "repo_configuration": [],
        "code_integrity": [],
        "ci_supply_chain": [],
        "collaborator_hygiene": [],
    }
    pass_count = 0
    advisory_count = 0
    for c in checks:
        check_name = _check_name_for(c)
        category = c.category or CHECK_CATEGORY.get(
            check_name, "repo_configuration"  # type: ignore[arg-type]
        )
        category_typed: PostureCheckCategory = category  # type: ignore[assignment]
        state, pr_url = _project_posture_state(c)
        wire = PostureCheckWire(
            name=check_name,
            display_name=CHECK_DISPLAY_NAME.get(check_name, check_name),  # type: ignore[arg-type]
            category=category_typed,
            state=state,
            grade_impact=_grade_impact_for(check_name),
            detail=(c.raw_payload or {}).get("detail", {}).get("reason")
            if isinstance(c.raw_payload, dict)
            and isinstance(c.raw_payload.get("detail"), dict)
            else None,
            pr_url=pr_url,
        )
        by_category.setdefault(category_typed, []).append(wire)
        if state == "advisory":
            advisory_count += 1
        elif state in ("pass", "done"):
            pass_count += 1

    categories: list[PostureCategoryWire] = []
    for cat, items in by_category.items():
        if not items:
            continue
        non_advisory = [it for it in items if it.grade_impact == "counts"]
        progress = CategoryProgress(
            done=sum(1 for it in non_advisory if it.state in ("pass", "done")),
            total=len(non_advisory),
        )
        categories.append(
            PostureCategoryWire(
                name=cat,
                display_name=_CATEGORY_DISPLAY[cat],
                progress=progress,
                checks=items,
            )
        )
    total = sum(
        1 for c in checks if _grade_impact_for(_check_name_for(c)) == "counts"
    )
    return PostureWire(
        pass_count=pass_count,
        total_count=total,
        advisory_count=advisory_count,
        categories=categories,
    )


_TYPE_TO_SOURCE = {
    "dependency": "dependency",
    "secret": "secret",
    "code": "code",
}


async def _build_vuln_counts(db, assessment_id: str) -> VulnerabilityCounts:
    findings = await list_findings(
        db,
        type=["dependency", "secret", "code"],
        assessment_id=assessment_id,
        limit=10_000,
    )
    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_source: dict[str, int] = {"dependency": 0, "code": 0, "secret": 0}
    credits: set[str] = set()
    for f in findings:
        if f.normalized_priority and f.normalized_priority in by_severity:
            by_severity[f.normalized_priority] += 1
        source_kind = _TYPE_TO_SOURCE.get(f.type, "dependency")
        by_source[source_kind] = by_source.get(source_kind, 0) + 1
        if f.source_type:
            credits.add(f.source_type)
    return VulnerabilityCounts(
        total=len(findings),
        by_severity=by_severity,
        by_source=by_source,
        tool_credits=sorted(credits),
    )


def _synthesize_tools(
    persisted: list[AssessmentTool] | None,
    pass_count: int,
    total_count: int,
    vulns: VulnerabilityCounts | None,
) -> list[AssessmentTool]:
    if persisted:
        return persisted
    by_source = (vulns.by_source if vulns else {}) or {}
    dep_count = by_source.get("dependency", 0) + by_source.get("secret", 0)
    code_count = by_source.get("code", 0)
    return [
        AssessmentTool(
            id="trivy",
            label="Trivy",
            version=None,
            icon="bug_report",
            state="done",
            result=AssessmentToolResult(
                kind="findings_count",
                value=dep_count,
                text=f"{dep_count} {'finding' if dep_count == 1 else 'findings'}",
            ),
        ),
        AssessmentTool(
            id="semgrep",
            label="Semgrep",
            version=None,
            icon="code",
            state="done",
            result=AssessmentToolResult(
                kind="findings_count",
                value=code_count,
                text=f"{code_count} {'finding' if code_count == 1 else 'findings'}",
            ),
        ),
        AssessmentTool(
            id="posture",
            label=f"{total_count} posture checks",
            version=None,
            icon="rule",
            state="done",
            result=AssessmentToolResult(
                kind="pass_count", value=pass_count, text=f"{pass_count} pass"
            ),
        ),
    ]


# ------------------------------------------------------------------ endpoint
@router.get("", response_model=DashboardPayload)
async def get_dashboard(db=Depends(get_db)) -> DashboardPayload:
    latest = await get_latest_assessment(db)
    phase2 = await assemble_phase2_metrics(db)

    if latest is None:
        empty_snapshot = CriteriaSnapshot()
        return DashboardPayload(
            assessment=None,
            grade=None,
            criteria=_criteria_to_labeled(empty_snapshot),
            criteria_snapshot=empty_snapshot,
            findings_count_by_priority={},
            posture_pass_count=0,
            posture_total_count=0,
            posture_checks=[],
            posture=None,
            tools=[],
            vulnerabilities=None,
            completion_id=None,
            open_issues=OpenIssuesSeries(**phase2["open_issues"]),
            time_to_close=TimeToCloseSeries(**phase2["time_to_close"]),
            needs_you=NeedsYouCounts(**phase2["needs_you"]),
            grade_history=[
                GradeHistoryPoint(**p) for p in phase2["grade_history"]
            ],
            severity_history=SeverityHistory(**phase2["severity_history"]),
        )

    counts = await count_findings_by_priority(
        db,
        type="dependency",
        assessment_id=latest.id,
    )
    posture_checks = await list_posture_findings(db, latest.id)
    pass_count = sum(
        1
        for c in posture_checks
        if c.status == "passed" and c.grade_impact == "counts"
    )
    total_count = sum(1 for c in posture_checks if c.grade_impact == "counts")
    completion = await get_completion_for_assessment(db, latest.id)
    vulnerabilities = await _build_vuln_counts(db, latest.id)

    snapshot = latest.criteria_snapshot or CriteriaSnapshot()
    completion_id = (
        completion.id
        if completion is not None and latest.grade == "A" and snapshot.all_met()
        else None
    )

    posture_wire = _build_posture_payload(posture_checks)
    tools = _synthesize_tools(latest.tools, pass_count, total_count, vulnerabilities)

    return DashboardPayload(
        assessment=latest,
        grade=latest.grade,
        criteria=_criteria_to_labeled(snapshot),
        criteria_snapshot=snapshot,
        findings_count_by_priority=counts,
        posture_pass_count=pass_count,
        posture_total_count=total_count,
        posture_checks=posture_checks,
        posture=posture_wire,
        tools=tools,
        vulnerabilities=vulnerabilities,
        completion_id=completion_id,
        open_issues=OpenIssuesSeries(**phase2["open_issues"]),
        time_to_close=TimeToCloseSeries(**phase2["time_to_close"]),
        needs_you=NeedsYouCounts(**phase2["needs_you"]),
        grade_history=[GradeHistoryPoint(**p) for p in phase2["grade_history"]],
        severity_history=SeverityHistory(**phase2["severity_history"]),
    )
