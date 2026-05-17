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


# ──────────────────────────────────────────────────────────────────────────
# IMPL-0009 — engine instrumentation: duration / scope / ran / commit / counts
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def planted_repo_with_npm_lockfile(tmp_path: Path) -> Path:
    """Repo with a tiny package-lock.json so dep-count helpers find something."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "demo", "version": "1.0.0"},
                    "node_modules/lodash": {"version": "4.17.21"},
                    "node_modules/axios": {"version": "1.6.0"},
                    "node_modules/express": {"version": "4.19.0"},
                },
            }
        )
    )
    (tmp_path / "package.json").write_text(json.dumps({"name": "demo", "version": "1.0.0"}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("console.log('hi')\n")
    return tmp_path


@pytest.mark.asyncio
async def test_engine_emits_three_tools_with_duration_scope_and_ran(
    planted_repo_with_npm_lockfile: Path,
) -> None:
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo_with_npm_lockfile)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-impl0009-1",
    )

    assert len(result.tools) == 3
    by_id = {t.id: t for t in result.tools}
    for tid in ("trivy", "semgrep", "posture"):
        tool = by_id[tid]
        assert tool.duration_ms is not None and tool.duration_ms >= 0, (
            f"{tid} duration_ms must be set"
        )
        assert tool.scope, f"{tid} scope must be a non-empty string"
        assert tool.ran, f"{tid} ran must be a non-empty string"


@pytest.mark.asyncio
async def test_engine_trivy_row_describes_combined_dependency_and_secret_scan(
    planted_repo_with_npm_lockfile: Path,
) -> None:
    """CEO call 2026-05-04 — Trivy is one invocation labelled accordingly."""
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo_with_npm_lockfile)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-impl0009-2",
    )

    trivy = next(t for t in result.tools if t.id == "trivy")
    assert trivy.ran == "Dependency + secret scan"
    assert "git history" in (trivy.scope or "")
    # Combined findings = vulns + secrets summed into one row (already true,
    # but re-asserted to lock the contract).
    assert trivy.result is not None
    fixture = _trivy_result_from_fixture()
    assert trivy.result.value == len(fixture.vulnerabilities) + len(fixture.secrets)


@pytest.mark.asyncio
async def test_engine_posture_tool_has_pinned_version(
    planted_repo_with_npm_lockfile: Path,
) -> None:
    """B5: posture has a version constant we set deliberately."""
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo_with_npm_lockfile)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-impl0009-3",
    )

    posture = next(t for t in result.tools if t.id == "posture")
    assert posture.version == "1.0.0"


@pytest.mark.asyncio
async def test_engine_assessment_result_carries_scope_fields(
    planted_repo_with_npm_lockfile: Path,
) -> None:
    """The AssessmentResult carries branch + counts so the route can persist."""
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo_with_npm_lockfile)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=_gh_client_unable(),
        runner=runner,
        cloner=cloner,
        assessment_id="asm-impl0009-4",
        branch="release/1",
    )

    assert result.branch == "release/1"
    assert result.scanned_files is not None and result.scanned_files > 0
    assert result.scanned_deps is not None and result.scanned_deps >= 3  # 3 npm deps planted
    # commit_sha is captured opportunistically via ``git rev-parse``; on the
    # planted (non-git) tmpdir it is ``None``. Real clones pick it up. Assert
    # the field is reachable as a string-or-None and didn't raise.
    assert result.commit_sha is None or isinstance(result.commit_sha, str)


# Q01R-B23 — when the caller doesn't pin a branch, the engine resolves the
# repo's real default via ``GET /repos/{owner}/{repo}`` and threads it
# through every posture probe. Without this fix, every NodeGoat-vintage
# (``master``-default) repo got 403/404 on branch protection + recent
# commits because RepoCoords silently defaulted to "main".


@pytest.mark.asyncio
async def test_engine_resolves_default_branch_when_branch_arg_is_none(
    planted_repo: Path,
) -> None:
    gh = AsyncMock()
    gh.get_repo_info.return_value = {"default_branch": "master"}
    gh.get_branch_protection.return_value = None
    gh.list_recent_commits.return_value = []
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/legacy",
        gh_client=gh,
        runner=runner,
        cloner=cloner,
        assessment_id="asm-b23-master",
        branch=None,
    )

    info_calls = [c.args for c in gh.get_repo_info.await_args_list]
    assert ("acme", "legacy") in info_calls, info_calls
    # ``get_branch_protection`` is also exercised by
    # ``default_branch_permissions``, so we assert presence-of-call with
    # the master ref rather than exact count.
    bp_calls = [c.args for c in gh.get_branch_protection.await_args_list]
    assert ("acme", "legacy", "master") in bp_calls, bp_calls
    gh.list_recent_commits.assert_awaited_once_with("acme", "legacy", "master")
    assert result.branch == "master"


@pytest.mark.asyncio
async def test_engine_resolves_default_branch_main_for_modern_repos(
    planted_repo: Path,
) -> None:
    gh = AsyncMock()
    gh.get_repo_info.return_value = {"default_branch": "main"}
    gh.get_branch_protection.return_value = None
    gh.list_recent_commits.return_value = []
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/modern",
        gh_client=gh,
        runner=runner,
        cloner=cloner,
        assessment_id="asm-b23-main",
        branch=None,
    )

    bp_calls = [c.args for c in gh.get_branch_protection.await_args_list]
    assert ("acme", "modern", "main") in bp_calls, bp_calls
    gh.list_recent_commits.assert_awaited_once_with("acme", "modern", "main")
    assert result.branch == "main"


@pytest.mark.asyncio
async def test_engine_falls_back_to_main_when_default_branch_lookup_fails(
    planted_repo: Path,
) -> None:
    """``get_repo_info`` returning ``UnableToVerify`` (rate limit / forbidden
    / network) must not abort the assessment. Fall back to ``main`` so the
    posture checks degrade to ``unknown`` for branch-scoped probes instead
    of failing the whole run.
    """
    gh = AsyncMock()
    gh.get_repo_info.return_value = UnableToVerify(reason="http_403")
    gh.get_branch_protection.return_value = UnableToVerify(reason="http_403")
    gh.list_recent_commits.return_value = []
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/locked",
        gh_client=gh,
        runner=runner,
        cloner=cloner,
        assessment_id="asm-b23-unable",
        branch=None,
    )

    # The default-branch resolver fires (at minimum) once; downstream
    # posture checks may also call ``get_repo_info`` for their own
    # purposes, so we assert presence rather than exact count.
    info_calls = [c.args for c in gh.get_repo_info.await_args_list]
    assert ("acme", "locked") in info_calls, info_calls
    # Falls back to ``main`` so the run completes; the per-check probe will
    # land as ``unknown`` if the branch genuinely doesn't exist.
    bp_calls = [c.args for c in gh.get_branch_protection.await_args_list]
    assert ("acme", "locked", "main") in bp_calls, bp_calls
    assert result.branch == "main"


@pytest.mark.asyncio
async def test_engine_honours_explicit_branch_kwarg_over_default_branch_lookup(
    planted_repo: Path,
) -> None:
    """When the caller already knows the branch (e.g. a re-scan triggered
    from a finding on a specific ref), the explicit value wins — the
    default-branch resolver in ``run_assessment`` is bypassed and the value
    flows verbatim into every branch-scoped probe.
    """
    gh = AsyncMock()
    gh.get_repo_info.return_value = {"default_branch": "main"}  # would be wrong
    gh.get_branch_protection.return_value = None
    gh.list_recent_commits.return_value = []
    runner = FakeScannerRunner()
    cloner = FakeRepoCloner(planted_repo)

    result = await run_assessment(
        "https://github.com/acme/demo",
        gh_client=gh,
        runner=runner,
        cloner=cloner,
        assessment_id="asm-b23-explicit",
        branch="release/2",
    )

    # ``get_repo_info`` is exercised by downstream posture checks
    # (``secret_scanning_enabled``, ``default_branch_permissions``) as part
    # of their normal probes — the assertion that matters is that the
    # explicit branch reached the branch-scoped calls verbatim, not via
    # the resolver's "default_branch" field.
    bp_calls = [c.args for c in gh.get_branch_protection.await_args_list]
    assert ("acme", "demo", "release/2") in bp_calls, bp_calls
    gh.list_recent_commits.assert_awaited_once_with("acme", "demo", "release/2")
    assert result.branch == "release/2"
