"""Assessment orchestrator (PRD-0003 v0.2 / IMPL-0003-p2 Phase 2).

`run_assessment` is the canonical entry point for a full repo scan. It clones
the target repo, runs Trivy + Semgrep via the :class:`ScannerRunner` (ADR-0028
subprocess-only execution), runs the 15 posture checks (PRD-0003 rev. 2), and
returns an :class:`AssessmentResult` with the full ``tools[]`` payload from
ADR-0032 already populated.

Persistence happens inline (Phase 2): when ``db`` is provided, each scanner's
output is mapped to ``FindingCreate`` rows via :mod:`opensec.assessment.to_findings`
and UPSERTed into the unified ``finding`` table; after every scanner that ran
successfully, a stale-close pass scoped by ``source_type`` marks rows that
disappeared between runs.

Trivy failure is fatal; Semgrep failure is graceful (the tool becomes
``skipped`` and the assessment continues without it). Per-check posture
``unknown`` is absorbed by the orchestrator and never raises.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from opensec.assessment.clone import shallow_clone
from opensec.assessment.posture import RepoCoords, run_all_posture_checks
from opensec.assessment.to_findings import (
    from_posture,
    from_semgrep,
    from_trivy_secrets,
    from_trivy_vulns,
)
from opensec.models.assessment import (
    AssessmentResult,
    AssessmentTool,
    AssessmentToolResult,
    CriteriaSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import aiosqlite

    from opensec.assessment.posture import GithubAPI, PostureCheckResult
    from opensec.assessment.scanners.models import (
        SemgrepResult,
        TrivyResult,
    )
    from opensec.assessment.scanners.runner import ScannerRunner
    from opensec.models.assessment import Grade
    from opensec.models.finding import FindingCreate
    from opensec.models.posture_check import PostureCheckName, PostureCheckStatus

logger = logging.getLogger(__name__)


_TRIVY_TIMEOUT_S: float = 120.0
_SEMGREP_TIMEOUT_S: float = 120.0
_CLONE_TIMEOUT_S: float = 60.0


# --------------------------------------------------------------------- cloning


class RepoCloner:
    """Async context manager around :func:`shallow_clone` (ADR-0024)."""

    def __init__(
        self,
        *,
        token_provider: Callable[[], Awaitable[str | None]] | None = None,
        tmp_root: Path | None = None,
        timeout_s: float = _CLONE_TIMEOUT_S,
    ) -> None:
        self._token_provider = token_provider
        self._tmp_root = tmp_root
        self._timeout_s = timeout_s

    @contextlib.asynccontextmanager
    async def clone(
        self, repo_url: str, *, branch: str = "main"
    ) -> AsyncIterator[Path]:
        del branch  # ``shallow_clone`` already uses ``--single-branch``.
        token: str | None = None
        if self._token_provider is not None:
            token = await self._token_provider()

        if self._tmp_root is not None:
            self._tmp_root.mkdir(parents=True, exist_ok=True)

        tmp_root_str = str(self._tmp_root) if self._tmp_root else None
        tmp = Path(tempfile.mkdtemp(prefix="opensec-clone-", dir=tmp_root_str))
        try:
            target = tmp / "repo"
            target.mkdir()
            await shallow_clone(
                repo_url, target=target, token=token, timeout_s=self._timeout_s
            )
            yield target
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------- engine


async def run_assessment(
    repo_url: str,
    *,
    gh_client: GithubAPI,
    runner: ScannerRunner,
    cloner: RepoCloner,
    assessment_id: str,
    db: aiosqlite.Connection | None = None,
    on_step: Callable[[str], Awaitable[None]] | None = None,
    on_tool: Callable[[AssessmentTool], Awaitable[None]] | None = None,
    branch: str = "main",
) -> AssessmentResult:
    """Clone -> Trivy -> Semgrep -> posture -> persist -> close-pass -> assemble.

    When ``db`` is provided, every scanner's output is mapped via
    :mod:`opensec.assessment.to_findings` and UPSERTed into the unified
    ``finding`` table; after each scanner that ran successfully, the
    stale-close pass marks prior rows for that ``source_type`` whose
    ``source_id`` disappeared this run as ``status='closed'``. When ``db`` is
    ``None`` (test mode), the engine still computes counts and emits the
    callbacks but does not touch the DB.
    """
    coords = _coords_from_repo_url(repo_url, branch=branch)

    tools: dict[str, AssessmentTool] = {
        "trivy": AssessmentTool(
            id="trivy", label="Trivy", icon="bug_report", state="pending"
        ),
        "semgrep": AssessmentTool(
            id="semgrep", label="Semgrep", icon="code", state="pending"
        ),
        "posture": AssessmentTool(
            id="posture", label="15 posture checks", icon="rule", state="pending"
        ),
    }
    for tool in tools.values():
        await _emit_tool(on_tool, tool)

    await _emit_step(on_step, "detect")
    async with cloner.clone(repo_url, branch=branch) as repo_path:

        # ---- Trivy ----
        tools["trivy"] = tools["trivy"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["trivy"])
        await _emit_step(on_step, "trivy_vuln")
        try:
            trivy_result = await runner.run_trivy(
                repo_path, timeout=_TRIVY_TIMEOUT_S
            )
        except Exception:
            tools["trivy"] = tools["trivy"].model_copy(update={"state": "skipped"})
            await _emit_tool(on_tool, tools["trivy"])
            logger.exception("trivy failed; assessment is fatally failing")
            raise

        await _emit_step(on_step, "trivy_secret")

        # ---- Semgrep (graceful skip) ----
        tools["semgrep"] = tools["semgrep"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["semgrep"])
        await _emit_step(on_step, "semgrep")
        semgrep_result: SemgrepResult | None = None
        semgrep_ran = False
        try:
            semgrep_result = await runner.run_semgrep(
                repo_path, timeout=_SEMGREP_TIMEOUT_S
            )
            semgrep_ran = True
        except Exception:
            logger.warning("semgrep failed; continuing without it", exc_info=True)
            tools["semgrep"] = tools["semgrep"].model_copy(
                update={"state": "skipped"}
            )
            await _emit_tool(on_tool, tools["semgrep"])

        # ---- Posture ----
        tools["posture"] = tools["posture"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["posture"])
        await _emit_step(on_step, "posture")
        posture_results = await run_all_posture_checks(
            repo_path,
            gh_client=gh_client,
            coords=coords,
            assessment_id=assessment_id,
        )

    # ---- Persistence + close pass (Phase 2) ----
    if db is not None:
        await _persist_findings(
            db,
            repo_url=repo_url,
            assessment_id=assessment_id,
            trivy_result=trivy_result,
            semgrep_result=semgrep_result if semgrep_ran else None,
            posture_results=posture_results,
        )

    # ---- Finalize tool results ----
    trivy_count = len(trivy_result.vulnerabilities) + len(trivy_result.secrets)
    tools["trivy"] = tools["trivy"].model_copy(
        update={
            "state": "done",
            "version": trivy_result.version or None,
            "label": _label_for("Trivy", trivy_result.version),
            "result": AssessmentToolResult(
                kind="findings_count",
                value=trivy_count,
                text=_pluralize(trivy_count, "finding"),
            ),
        }
    )
    await _emit_tool(on_tool, tools["trivy"])

    if semgrep_ran and semgrep_result is not None:
        sg_count = len(semgrep_result.findings)
        tools["semgrep"] = tools["semgrep"].model_copy(
            update={
                "state": "done",
                "version": semgrep_result.version or None,
                "label": _label_for("Semgrep", semgrep_result.version),
                "result": AssessmentToolResult(
                    kind="findings_count",
                    value=sg_count,
                    text=_pluralize(sg_count, "finding"),
                ),
            }
        )
        await _emit_tool(on_tool, tools["semgrep"])

    posture_pass = sum(1 for pc in posture_results if pc.status == "pass")
    tools["posture"] = tools["posture"].model_copy(
        update={
            "state": "done",
            "result": AssessmentToolResult(
                kind="pass_count",
                value=posture_pass,
                text=f"{posture_pass} pass",
            ),
        }
    )
    await _emit_tool(on_tool, tools["posture"])

    # ---- Snapshot + grade ----
    await _emit_step(on_step, "descriptions")
    posture_statuses: dict[PostureCheckName, PostureCheckStatus] = {
        pc.check_name: pc.status for pc in posture_results
    }
    snapshot = _build_snapshot(trivy_result, semgrep_result, posture_statuses)
    grade = derive_grade(snapshot)

    return AssessmentResult(
        assessment_id=assessment_id,
        repo_url=repo_url,
        grade=grade,
        criteria_snapshot=snapshot,
        findings=[],  # persisted directly; the wire shape carries no dicts
        posture_checks=[
            {
                "check_name": pc.check_name,
                "status": pc.status,
                "detail": pc.detail,
            }
            for pc in posture_results
        ],
        tools=list(tools.values()),
    )


# --------------------------------------------------------------------- persistence


async def _persist_findings(
    db: aiosqlite.Connection,
    *,
    repo_url: str,
    assessment_id: str,
    trivy_result: TrivyResult,
    semgrep_result: SemgrepResult | None,
    posture_results: list[PostureCheckResult],
) -> None:
    """UPSERT scanner outputs and run the stale-close pass per source_type."""
    from opensec.db.repo_finding import (
        close_disappeared_findings,
        create_finding,
    )

    # 1. Map + UPSERT.
    trivy_vuln_rows = from_trivy_vulns(trivy_result, assessment_id=assessment_id)
    trivy_secret_rows = from_trivy_secrets(
        trivy_result, assessment_id=assessment_id
    )
    semgrep_rows: list[FindingCreate] = []
    if semgrep_result is not None:
        semgrep_rows = from_semgrep(semgrep_result, assessment_id=assessment_id)
    posture_rows = from_posture(
        posture_results, repo_url=repo_url, assessment_id=assessment_id
    )

    for row in (*trivy_vuln_rows, *trivy_secret_rows, *semgrep_rows, *posture_rows):
        try:
            await create_finding(db, row)
        except Exception:
            logger.exception(
                "create_finding failed for source_type=%s source_id=%s",
                row.source_type,
                row.source_id,
            )

    # 2. Close pass per source_type that ran successfully. Posture is
    # excluded — every scan rewrites every check, so there's no
    # "disappearance" to detect; a check that was failing and now passes is
    # already handled by the type-conditional UPSERT.
    await close_disappeared_findings(
        db,
        source_type="trivy",
        kept_source_ids=[r.source_id for r in trivy_vuln_rows],
        assessment_id=assessment_id,
        repo_url=repo_url,
    )
    await close_disappeared_findings(
        db,
        source_type="trivy-secret",
        kept_source_ids=[r.source_id for r in trivy_secret_rows],
        assessment_id=assessment_id,
        repo_url=repo_url,
    )
    if semgrep_result is not None:
        await close_disappeared_findings(
            db,
            source_type="semgrep",
            kept_source_ids=[r.source_id for r in semgrep_rows],
            assessment_id=assessment_id,
            repo_url=repo_url,
        )


# --------------------------------------------------------------------- helpers


async def _emit_step(
    cb: Callable[[str], Awaitable[None]] | None, step: str
) -> None:
    if cb is None:
        return
    try:
        await cb(step)
    except Exception:  # noqa: BLE001
        logger.debug("on_step callback raised for step=%s", step, exc_info=True)


async def _emit_tool(
    cb: Callable[[AssessmentTool], Awaitable[None]] | None,
    tool: AssessmentTool,
) -> None:
    if cb is None:
        return
    try:
        await cb(tool)
    except Exception:  # noqa: BLE001
        logger.debug("on_tool callback raised for tool=%s", tool.id, exc_info=True)


def _label_for(name: str, version: str | None) -> str:
    if version and version != "unknown":
        return f"{name} {version}"
    return name


def _pluralize(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def derive_grade(criteria: CriteriaSnapshot, *_args: Any, **_kwargs: Any) -> Grade:
    """Ten-criteria grading per PRD-0003 v0.2 / ADR-0032.

    A=10, B=8-9, C=6-7, D=4-5, F=0-3. Extra positional/keyword args are
    accepted for backward compatibility with legacy call sites that passed
    ``findings`` and ``posture_statuses`` — those values are ignored because
    the snapshot is now authoritative end-to-end.
    """
    met = criteria.met_count()
    if met == 10:
        return "A"
    if met >= 8:
        return "B"
    if met >= 6:
        return "C"
    if met >= 4:
        return "D"
    return "F"


def _build_snapshot(
    trivy_result: TrivyResult,
    semgrep_result: SemgrepResult | None,
    posture_statuses: dict[PostureCheckName, PostureCheckStatus],
) -> CriteriaSnapshot:
    severities: set[str] = set()
    for v in trivy_result.vulnerabilities:
        severities.add((v.severity or "").upper())
    for s in trivy_result.secrets:
        severities.add((s.severity or "").upper())
    if semgrep_result is not None:
        for f in semgrep_result.findings:
            severities.add((f.severity or "").upper())
    has_unknown = "UNKNOWN" in severities
    passing = sum(1 for s in posture_statuses.values() if s == "pass")

    def _tri(check: PostureCheckName) -> bool | None:
        """Map a posture-check status to the criteria tri-state.

        ``pass`` → True, ``fail`` → False, ``unknown`` (or check missing,
        e.g. the daemon has no GitHub token to evaluate it) → None.
        ``advisory`` collapses to False because advisory checks aren't
        grade-counting and shouldn't claim "pass" toward Grade A.
        """
        status = posture_statuses.get(check)
        if status == "pass":
            return True
        if status is None or status == "unknown":
            return None
        return False

    return CriteriaSnapshot(
        no_critical_vulns="CRITICAL" not in severities and not has_unknown,
        no_high_vulns=(
            "HIGH" not in severities
            and "CRITICAL" not in severities
            and "ERROR" not in severities
            and not has_unknown
        ),
        posture_checks_passing=passing,
        posture_checks_total=len(posture_statuses),
        security_md_present=_tri("security_md"),
        dependabot_present=_tri("dependabot_config"),
        branch_protection_enabled=_tri("branch_protection"),
        no_secrets_detected=_tri("no_secrets_in_code"),
        actions_pinned_to_sha=_tri("actions_pinned_to_sha"),
        no_stale_collaborators=_tri("stale_collaborators"),
        code_owners_exists=_tri("code_owners_exists"),
        secret_scanning_enabled=_tri("secret_scanning_enabled"),
    )


def _coords_from_repo_url(repo_url: str, *, branch: str) -> RepoCoords:
    """Parse `owner/repo` out of an HTTPS or SSH URL."""
    if repo_url.startswith("git@") and ":" in repo_url:
        path = repo_url.split(":", 1)[1]
    else:
        parsed = urlparse(repo_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"cannot parse owner/repo from repo_url: {repo_url!r}")
        path = parsed.path

    path = path.strip("/").removesuffix(".git")
    owner, _, repo = path.partition("/")
    if not owner or not repo:
        raise ValueError(f"cannot parse owner/repo from repo_url: {repo_url!r}")
    return RepoCoords(owner=owner, repo=repo, branch=branch)


__all__ = [
    "RepoCloner",
    "_coords_from_repo_url",
    "derive_grade",
    "run_assessment",
]
