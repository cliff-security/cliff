"""FakeAssessmentEngine — test double standing in for the real engine.

Conforms to ``AssessmentEngineProtocol``. Returns a canned ``AssessmentResult``
so route tests can exercise the full happy path without touching subprocesses
or the network. Updated for PR-B (PRD-0003 v0.2): emits the six v0.2 step keys
and supports the ``on_tool`` callback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.models import (
    AssessmentResult,
    AssessmentTool,
    AssessmentToolResult,
    CriteriaSnapshot,
    Grade,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _default_tools() -> list[AssessmentTool]:
    return [
        AssessmentTool(
            id="trivy",
            label="Trivy 0.52.0",
            version="0.52.0",
            icon="bug_report",
            state="done",
            result=AssessmentToolResult(
                kind="findings_count", value=0, text="0 findings"
            ),
        ),
        AssessmentTool(
            id="semgrep",
            label="Semgrep 1.70.0",
            version="1.70.0",
            icon="code",
            state="done",
            result=AssessmentToolResult(
                kind="findings_count", value=0, text="0 findings"
            ),
        ),
        AssessmentTool(
            id="posture",
            label="15 posture checks",
            version=None,
            icon="rule",
            state="done",
            result=AssessmentToolResult(
                kind="pass_count", value=0, text="0 pass"
            ),
        ),
    ]


class FakeAssessmentEngine:
    """In-memory stub that mirrors the v0.2 engine interface."""

    def __init__(
        self,
        *,
        grade: Grade = "B",
        criteria: CriteriaSnapshot | None = None,
        posture_checks: list[dict] | None = None,
        findings: list[dict] | None = None,
        tools: list[AssessmentTool] | None = None,
        raise_on_run: Exception | None = None,
    ) -> None:
        self.grade = grade
        self.criteria = criteria or CriteriaSnapshot(
            no_critical_vulns=True,
            posture_checks_passing=3,
            posture_checks_total=5,
            security_md_present=True,
            dependabot_present=False,
        )
        self.posture_checks = posture_checks if posture_checks is not None else [
            {"check_name": "branch_protection", "status": "pass"},
            {"check_name": "signed_commits", "status": "advisory"},
        ]
        self.findings = findings or []
        self.tools = tools if tools is not None else _default_tools()
        self.raise_on_run = raise_on_run
        self.call_count = 0

    async def run_assessment(
        self,
        repo_url: str,
        *,
        assessment_id: str,
        db: object | None = None,
        on_step: Callable[[str], Awaitable[None]] | None = None,
        on_tool: Callable[[AssessmentTool], Awaitable[None]] | None = None,
    ) -> AssessmentResult:
        self.call_count += 1
        # Persist test-injected findings + posture results so route tests that
        # exercise the full background flow can read them back from
        # ``list_findings`` / ``list_posture_findings``.
        if db is not None:
            import contextlib

            from cliff.assessment.posture import ADVISORY_CHECKS, CHECK_CATEGORY
            from cliff.db.repo_finding import create_finding
            from cliff.models import FindingCreate

            for f in self.findings:
                payload = {**f}
                payload.setdefault("assessment_id", assessment_id)
                with contextlib.suppress(Exception):
                    await create_finding(db, FindingCreate(**payload))

            for pc in self.posture_checks:
                name = pc.get("check_name")
                scanner_status = pc.get("status", "pass")
                if scanner_status == "unknown":
                    continue
                is_advisory = (
                    name in ADVISORY_CHECKS or scanner_status == "advisory"
                )
                if is_advisory:
                    grade_impact = "advisory"
                    status = "new"
                elif scanner_status == "pass":
                    grade_impact = "counts"
                    status = "passed"
                else:
                    grade_impact = "counts"
                    status = "new"
                with contextlib.suppress(Exception):
                    await create_finding(
                        db,
                        FindingCreate(
                            source_type="cliff-posture",
                            source_id=f"{repo_url}:{name}",
                            type="posture",
                            grade_impact=grade_impact,
                            category=CHECK_CATEGORY.get(  # type: ignore[arg-type]
                                name, "repo_configuration"
                            ),
                            assessment_id=assessment_id,
                            status=status,
                            title=str(name),
                            pr_url=pc.get("pr_url"),
                            raw_payload={
                                "check_name": name,
                                "scanner_status": scanner_status,
                            },
                        ),
                    )
        if on_step is not None:
            # Mirror the real engine's six v0.2 phase keys so route tests that
            # poll ``GET /assessment/status`` get realistic step values.
            for step in (
                "detect",
                "trivy_vuln",
                "trivy_secret",
                "semgrep",
                "posture",
                "descriptions",
            ):
                await on_step(step)
        if on_tool is not None:
            for tool in self.tools:
                await on_tool(tool)
        if self.raise_on_run is not None:
            raise self.raise_on_run
        return AssessmentResult(
            assessment_id=assessment_id,
            repo_url=repo_url,
            grade=self.grade,
            criteria_snapshot=self.criteria,
            findings=self.findings,
            posture_checks=self.posture_checks,
            tools=self.tools,
        )
