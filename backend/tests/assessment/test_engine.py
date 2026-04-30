"""Engine tests for the v0.2 pipeline (PRD-0003 / IMPL-0003-p2 Phase 1).

Drives ``run_assessment`` against a fake :class:`ScannerRunner` that returns
canned :class:`TrivyResult` / :class:`SemgrepResult` objects, plus a fake
:class:`RepoCloner` that yields a temp directory. Posture is exercised via
``AsyncMock``-backed GitHub client so we don't depend on real network or
filesystem state.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from opensec.assessment.engine import (
    RepoCloner,
    _coords_from_repo_url,
    derive_grade,
    run_assessment,
)
from opensec.assessment.posture.github_client import UnableToVerify
from opensec.assessment.scanners.models import (
    SemgrepFinding,
    SemgrepResult,
    TrivyResult,
    TrivySecret,
    TrivyVulnerability,
)
from opensec.models.assessment import AssessmentTool, CriteriaSnapshot

FIXTURES = Path(__file__).parent.parent / "fixtures"


# --------------------------------------------------------------------- helpers


def _trivy_result_from_fixture() -> TrivyResult:
    payload = json.loads((FIXTURES / "scanners" / "trivy_output.json").read_text())
    vulns: list[TrivyVulnerability] = []
    secrets: list[TrivySecret] = []
    for result in payload.get("Results", []):
        for v in result.get("Vulnerabilities", []) or []:
            vulns.append(
                TrivyVulnerability(
                    pkg_name=v["PkgName"],
                    installed_version=v["InstalledVersion"],
                    vuln_id=v["VulnerabilityID"],
                    severity=v["Severity"],
                    title=v["Title"],
                    primary_url=v.get("PrimaryURL"),
                    fixed_version=v.get("FixedVersion"),
                    description=v.get("Description"),
                )
            )
        for s in result.get("Secrets", []) or []:
            secrets.append(
                TrivySecret(
                    rule_id=s["RuleID"],
                    category=s["Category"],
                    severity=s["Severity"],
                    title=s["Title"],
                    path=result["Target"],
                    start_line=int(s.get("StartLine") or 0),
                    end_line=s.get("EndLine"),
                    match=s.get("Match"),
                )
            )
    return TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        vulnerabilities=vulns,
        secrets=secrets,
    )


def _semgrep_result_from_fixture() -> SemgrepResult:
    payload = json.loads((FIXTURES / "scanners" / "semgrep_output.json").read_text())
    findings: list[SemgrepFinding] = []
    for r in payload["results"]:
        findings.append(
            SemgrepFinding(
                check_id=r["check_id"],
                path=r["path"],
                start_line=r["start"]["line"],
                end_line=r["end"]["line"],
                severity=r["extra"]["severity"],
                message=r["extra"]["message"],
                cwe=r["extra"].get("metadata", {}).get("cwe", []),
            )
        )
    return SemgrepResult(
        version=payload.get("version", "1.70.0"),
        findings=findings,
    )


class FakeScannerRunner:
    """Captures call args for assertion; returns canned results."""

    def __init__(
        self,
        *,
        trivy_result: TrivyResult | None = None,
        semgrep_result: SemgrepResult | None = None,
        trivy_exc: Exception | None = None,
        semgrep_exc: Exception | None = None,
    ) -> None:
        self._trivy_result = trivy_result or _trivy_result_from_fixture()
        self._semgrep_result = semgrep_result or _semgrep_result_from_fixture()
        self._trivy_exc = trivy_exc
        self._semgrep_exc = semgrep_exc
        self.trivy_calls: list[Path] = []
        self.semgrep_calls: list[Path] = []

    async def run_trivy(self, target_dir: Path, *, timeout: float) -> TrivyResult:
        self.trivy_calls.append(target_dir)
        if self._trivy_exc is not None:
            raise self._trivy_exc
        return self._trivy_result

    async def run_semgrep(self, target_dir: Path, *, timeout: float) -> SemgrepResult:
        self.semgrep_calls.append(target_dir)
        if self._semgrep_exc is not None:
            raise self._semgrep_exc
        return self._semgrep_result

    def available_scanners(self) -> list[Any]:  # protocol-completeness
        return []


class FakeRepoCloner(RepoCloner):
    """Cloner that yields a pre-baked directory; never shells out."""

    def __init__(self, repo_path: Path) -> None:
        super().__init__()
        self._repo_path = repo_path

    @asynccontextmanager
    async def clone(self, repo_url: str, *, branch: str = "main"):
        del repo_url, branch
        yield self._repo_path


def _gh_client_unable() -> AsyncMock:
    """A GitHub client where every probe returns ``UnableToVerify``.

    Used to drive the per-check ``unknown`` path; the orchestrator absorbs
    these and continues, never aborts the run.
    """
    gh = AsyncMock()
    gh.get_branch_protection.return_value = UnableToVerify(reason="http_403")
    gh.list_recent_commits.return_value = []
    return gh


@pytest.fixture
def planted_repo(tmp_path: Path) -> Path:
    """A minimal repo on disk so posture filesystem checks have something."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"name": "demo", "lockfileVersion": 3, "packages": {}})
    )
    return tmp_path


# --------------------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_engine_step_reporting_emits_six_keys_in_order(
    planted_repo: Path,
) -> None:
    """The engine emits the six v0.2 step keys in order (PRD-0003 / ADR-0032)."""
    steps: list[str] = []

    async def on_step(step: str) -> None:
        steps.append(step)

    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-1",
        on_step=on_step,
    )

    assert steps == [
        "detect",
        "trivy_vuln",
        "trivy_secret",
        "semgrep",
        "posture",
        "descriptions",
    ]


@pytest.mark.asyncio
async def test_engine_tools_emission_three_pills_pending_active_done(
    planted_repo: Path,
) -> None:
    """``on_tool`` fires for every state transition; final state is ``done``."""
    received: list[AssessmentTool] = []

    async def on_tool(tool: AssessmentTool) -> None:
        received.append(tool.model_copy(deep=True))

    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-2",
        on_tool=on_tool,
    )

    initial_pending = [t for t in received[:3] if t.state == "pending"]
    assert {t.id for t in initial_pending} == {"trivy", "semgrep", "posture"}

    final_by_id = {t.id: t for t in result.tools}
    assert final_by_id["trivy"].state == "done"
    assert final_by_id["trivy"].result is not None
    assert final_by_id["trivy"].result.kind == "findings_count"
    assert final_by_id["semgrep"].state == "done"
    assert final_by_id["semgrep"].result is not None
    assert final_by_id["posture"].state == "done"
    assert final_by_id["posture"].result is not None
    assert final_by_id["posture"].result.kind == "pass_count"

    by_id_states: dict[str, list[str]] = {"trivy": [], "semgrep": [], "posture": []}
    for tool in received:
        by_id_states[tool.id].append(tool.state)
    for tid in ("trivy", "semgrep", "posture"):
        assert by_id_states[tid][0] == "pending"
        assert "active" in by_id_states[tid]
        assert by_id_states[tid][-1] == "done"


@pytest.mark.asyncio
async def test_engine_trivy_failure_is_fatal(planted_repo: Path) -> None:
    received: list[AssessmentTool] = []

    async def on_tool(tool: AssessmentTool) -> None:
        received.append(tool.model_copy(deep=True))

    runner = FakeScannerRunner(trivy_exc=RuntimeError("trivy crashed"))
    cloner = FakeRepoCloner(planted_repo)

    with pytest.raises(RuntimeError, match="trivy crashed"):
        await run_assessment(
            "https://github.com/acme/demo",
            gh_client=_gh_client_unable(),
            runner=runner,
            cloner=cloner,
            assessment_id="asm-3",
            on_tool=on_tool,
        )

    trivy_states = [t.state for t in received if t.id == "trivy"]
    assert "skipped" in trivy_states


@pytest.mark.asyncio
async def test_engine_semgrep_failure_is_graceful_skipped_state(
    planted_repo: Path,
) -> None:
    runner = FakeScannerRunner(semgrep_exc=RuntimeError("semgrep crashed"))
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-4",
    )

    final_by_id = {t.id: t for t in result.tools}
    assert final_by_id["semgrep"].state == "skipped"
    assert final_by_id["trivy"].state == "done"
    assert final_by_id["posture"].state == "done"
    assert result.grade in {"A", "B", "C", "D", "F"}


@pytest.mark.asyncio
async def test_engine_clones_via_repo_cloner_and_uses_path_for_scanners(
    planted_repo: Path,
) -> None:
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-5",
    )

    assert runner.trivy_calls == [planted_repo]
    assert runner.semgrep_calls == [planted_repo]


@pytest.mark.asyncio
async def test_engine_returns_assessment_result_with_tools_payload(
    planted_repo: Path,
) -> None:
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-6",
    )

    assert result.assessment_id == "asm-6"
    assert result.repo_url == "https://github.com/acme/demo"
    assert len(result.tools) == 3
    assert {t.id for t in result.tools} == {"trivy", "semgrep", "posture"}
    trivy = next(t for t in result.tools if t.id == "trivy")
    assert trivy.version == "0.52.0"
    assert trivy.label == "Trivy 0.52.0"
    semgrep = next(t for t in result.tools if t.id == "semgrep")
    assert semgrep.version == "1.70.0"

    # Findings persist via the engine's UPSERT path when ``db`` is provided;
    # the in-memory result no longer carries dict findings (Phase 2). Posture
    # results are still surfaced through the in-memory list for inspection.
    assert result.findings == []
    assert len(result.posture_checks) == 15


@pytest.mark.asyncio
async def test_engine_posture_per_check_unknown_does_not_abort(
    planted_repo: Path,
) -> None:
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-7",
    )

    statuses = {pc["check_name"]: pc["status"] for pc in result.posture_checks}
    assert statuses["branch_protection"] == "unknown"
    assert statuses["lockfile_present"] == "pass"
    assert statuses["security_md"] == "fail"


# --------------------------------------------------------------------- coords


@pytest.mark.parametrize(
    "url,expected_owner,expected_repo",
    [
        ("https://github.com/acme/demo", "acme", "demo"),
        ("https://github.com/acme/demo.git", "acme", "demo"),
        ("https://github.com/acme/demo/", "acme", "demo"),
        ("git@github.com:acme/demo.git", "acme", "demo"),
        ("git@github.com:acme/demo", "acme", "demo"),
    ],
)
def test_coords_from_repo_url_handles_supported_forms(
    url: str, expected_owner: str, expected_repo: str
) -> None:
    coords = _coords_from_repo_url(url, branch="main")
    assert coords.owner == expected_owner
    assert coords.repo == expected_repo


@pytest.mark.parametrize(
    "url",
    ["not a url", "https://github.com/", "https://github.com/just-owner", ""],
)
def test_coords_from_repo_url_raises_on_malformed(url: str) -> None:
    with pytest.raises(ValueError, match="repo_url"):
        _coords_from_repo_url(url, branch="main")


# --------------------------------------------------------------------- grading


def test_derive_grade_a_when_all_ten_criteria_met() -> None:
    snap = CriteriaSnapshot(
        no_critical_vulns=True,
        no_high_vulns=True,
        security_md_present=True,
        dependabot_present=True,
        branch_protection_enabled=True,
        no_secrets_detected=True,
        actions_pinned_to_sha=True,
        no_stale_collaborators=True,
        code_owners_exists=True,
        secret_scanning_enabled=True,
        posture_checks_passing=15,
        posture_checks_total=15,
    )
    assert derive_grade(snap, [], {}) == "A"


def test_derive_grade_f_when_criticals_present() -> None:
    snap = CriteriaSnapshot(no_critical_vulns=False)
    findings = [{"raw_severity": "CRITICAL"}]
    posture_statuses = {"branch_protection": "fail", "no_secrets_in_code": "fail"}
    assert derive_grade(snap, findings, posture_statuses) == "F"


def test_derive_grade_uses_snapshot_directly() -> None:
    """v0.2: ``derive_grade`` reads ``CriteriaSnapshot.met_count()`` only.

    The engine's ``_build_snapshot`` does the severity + posture roll-up
    end-to-end, so ``derive_grade`` is now a pure function over the snapshot.
    Five out of ten criteria met → D.
    """
    snap = CriteriaSnapshot(
        security_md_present=True,
        dependabot_present=True,
        branch_protection_enabled=True,
        no_secrets_detected=True,
        no_critical_vulns=True,
    )
    assert snap.met_count() == 5
    assert derive_grade(snap) == "D"


def test_criteria_unknown_is_distinct_from_fail() -> None:
    """``None`` (unknown — could not verify) must round-trip and stay distinct
    from ``False`` (verified fail).

    Previously ``_build_snapshot`` collapsed both to ``False`` via
    ``status == "pass"`` shorthand, so a posture check that returned
    ``unknown`` (e.g. no GitHub token) was indistinguishable from a real
    failure. Frontend / CLI consumers couldn't render the third state.
    """
    snap = CriteriaSnapshot(
        no_critical_vulns=True,
        no_high_vulns=True,
        security_md_present=True,
        dependabot_present=True,
        no_secrets_detected=True,
        code_owners_exists=True,
        # Real verified failure:
        actions_pinned_to_sha=False,
        # Cannot verify (no PAT, etc.):
        branch_protection_enabled=None,
        no_stale_collaborators=None,
        secret_scanning_enabled=None,
    )
    # 6 verified-pass; 1 verified-fail; 3 unknown — only the 6 count.
    assert snap.met_count() == 6
    assert derive_grade(snap) == "C"
    # The three unknowns must serialize as ``null``, not ``false``.
    dumped = snap.model_dump()
    assert dumped["branch_protection_enabled"] is None
    assert dumped["no_stale_collaborators"] is None
    assert dumped["secret_scanning_enabled"] is None
    assert dumped["actions_pinned_to_sha"] is False  # real fail


def test_criteria_snapshot_10_fields() -> None:
    snap = CriteriaSnapshot()
    grading_fields = {
        "no_critical_vulns",
        "no_high_vulns",
        "security_md_present",
        "dependabot_present",
        "branch_protection_enabled",
        "no_secrets_detected",
        "actions_pinned_to_sha",
        "no_stale_collaborators",
        "code_owners_exists",
        "secret_scanning_enabled",
    }
    fields = set(snap.model_dump().keys())
    missing = grading_fields - fields
    assert not missing, f"missing grading criteria fields: {missing}"
    assert snap.met_count() == 0
