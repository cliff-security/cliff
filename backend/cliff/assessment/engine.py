"""Assessment orchestrator (PRD-0003 v0.2 / IMPL-0003-p2 Phase 2).

`run_assessment` is the canonical entry point for a full repo scan. It clones
the target repo, runs Trivy + Semgrep via the :class:`ScannerRunner` (ADR-0028
subprocess-only execution), runs the 15 posture checks (PRD-0003 rev. 2), and
returns an :class:`AssessmentResult` with the full ``tools[]`` payload from
ADR-0032 already populated.

Persistence happens inline (Phase 2): when ``db`` is provided, each scanner's
output is mapped to ``FindingCreate`` rows via :mod:`cliff.assessment.to_findings`
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
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from cliff.assessment.clone import shallow_clone
from cliff.assessment.posture import (
    POSTURE_CHECKER_VERSION,
    RepoCoords,
    run_all_posture_checks,
)
from cliff.assessment.scanners.runner import (
    SEMGREP_RULESETS_LABEL,
    ScannerTimeoutError,
)
from cliff.assessment.scope import (
    capture_commit_sha,
    count_dependencies,
    count_scanned_files,
    detect_ecosystems,
)
from cliff.assessment.to_findings import (
    from_posture,
    from_semgrep,
    from_trivy_secrets,
    from_trivy_vulns,
)
from cliff.models.assessment import (
    AssessmentResult,
    AssessmentTool,
    AssessmentToolResult,
    CriteriaSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import aiosqlite

    from cliff.assessment.posture import GithubAPI, PostureCheckResult
    from cliff.assessment.scanners.models import (
        SemgrepResult,
        TrivyResult,
    )
    from cliff.assessment.scanners.runner import ScannerRunner
    from cliff.models.assessment import Grade
    from cliff.models.finding import FindingCreate
    from cliff.models.posture_check import PostureCheckName, PostureCheckStatus

logger = logging.getLogger(__name__)


_TRIVY_TIMEOUT_S: float = 120.0
_CLONE_TIMEOUT_S: float = 60.0


def _semgrep_timeout_s() -> float:
    """Semgrep's per-run timeout budget (B07).

    The 120s default was too tight for large repos — a 6.6k-file repo
    reliably timed out, and the assessment then silently dropped all SAST
    coverage. 300s matches PRD-0003's 5-minute total-assessment budget as
    the per-scanner ceiling. ``CLIFF_SEMGREP_TIMEOUT_S`` lets operators of
    very large repos extend it without a rebuild.
    """
    raw = os.environ.get("CLIFF_SEMGREP_TIMEOUT_S")
    if raw:
        try:
            parsed = float(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            logger.warning(
                "ignoring invalid CLIFF_SEMGREP_TIMEOUT_S=%r; using default", raw
            )
    return 300.0


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
        tmp = Path(tempfile.mkdtemp(prefix="cliff-clone-", dir=tmp_root_str))
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
    branch: str | None = None,
) -> AssessmentResult:
    """Clone -> Trivy -> Semgrep -> posture -> persist -> close-pass -> assemble.

    When ``db`` is provided, every scanner's output is mapped via
    :mod:`cliff.assessment.to_findings` and UPSERTed into the unified
    ``finding`` table; after each scanner that ran successfully, the
    stale-close pass marks prior rows for that ``source_type`` whose
    ``source_id`` disappeared this run as ``status='closed'``. When ``db`` is
    ``None`` (test mode), the engine still computes counts and emits the
    callbacks but does not touch the DB.

    ``branch`` defaults to ``None``, in which case the engine resolves the
    repo's real default branch from ``GET /repos/{owner}/{repo}`` before any
    branch-scoped posture probe runs (Q01R-B23). If that lookup fails
    (rate-limited, forbidden, unauthenticated, network error), the engine
    falls back to ``main`` so the run completes — the branch-scoped probes
    will then degrade to ``unknown`` on a master-default repo rather than
    blowing up the whole assessment. Pass ``branch=...`` explicitly to skip
    the lookup when the caller already knows the ref.
    """
    owner, repo = _owner_repo_from_url(repo_url)
    resolved_branch = (
        branch if branch is not None else await _resolve_default_branch(gh_client, owner, repo)
    )
    coords = _coords_from_repo_url(repo_url, branch=resolved_branch)

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
    # IMPL-0009 — timing buckets per scanner (in milliseconds, populated as
    # each block transitions to ``done``/``skipped``).
    durations_ms: dict[str, int] = {}
    # Scope captured opportunistically once the clone is in hand.
    commit_sha: str | None = None
    scanned_files: int | None = None
    scanned_deps: int | None = None
    ecosystems: list[str] = []

    async with cloner.clone(repo_url, branch=resolved_branch) as repo_path:
        # Best-effort scope capture. None of these are critical-path; failures
        # are silently swallowed so an assessment never breaks over UI text.
        commit_sha = await capture_commit_sha(repo_path)
        try:
            scanned_files = count_scanned_files(repo_path)
        except OSError:
            scanned_files = None
        try:
            scanned_deps = count_dependencies(repo_path)
            ecosystems = detect_ecosystems(repo_path)
        except OSError:
            scanned_deps = None
            ecosystems = []

        # ---- Trivy ----
        tools["trivy"] = tools["trivy"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["trivy"])
        await _emit_step(on_step, "trivy_vuln")
        trivy_started = time.perf_counter()
        try:
            trivy_result = await runner.run_trivy(
                repo_path, timeout=_TRIVY_TIMEOUT_S
            )
        except Exception:
            durations_ms["trivy"] = _elapsed_ms(trivy_started)
            tools["trivy"] = tools["trivy"].model_copy(
                update={
                    "state": "skipped",
                    "duration_ms": durations_ms["trivy"],
                }
            )
            await _emit_tool(on_tool, tools["trivy"])
            logger.exception("trivy failed; assessment is fatally failing")
            raise
        durations_ms["trivy"] = _elapsed_ms(trivy_started)

        await _emit_step(on_step, "trivy_secret")

        # ---- Semgrep (graceful skip) ----
        tools["semgrep"] = tools["semgrep"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["semgrep"])
        await _emit_step(on_step, "semgrep")
        semgrep_result: SemgrepResult | None = None
        semgrep_ran = False
        semgrep_started = time.perf_counter()
        try:
            semgrep_result = await runner.run_semgrep(
                repo_path, timeout=_semgrep_timeout_s()
            )
            semgrep_ran = True
        except Exception as exc:
            logger.warning("semgrep failed; continuing without it", exc_info=True)
            durations_ms["semgrep"] = _elapsed_ms(semgrep_started)
            # B07 — carry a machine-readable reason so the dashboard can
            # render a skipped scanner distinctly from a clean "0 findings"
            # run. A timeout is the common case on large repos; anything
            # else is an exec failure.
            tool_error = (
                "timeout" if isinstance(exc, ScannerTimeoutError) else "exec_failed"
            )
            tools["semgrep"] = tools["semgrep"].model_copy(
                update={
                    "state": "skipped",
                    "duration_ms": durations_ms["semgrep"],
                    "error": tool_error,
                }
            )
            await _emit_tool(on_tool, tools["semgrep"])
        else:
            durations_ms["semgrep"] = _elapsed_ms(semgrep_started)

        # If Semgrep skipped, fall back to a recursive walk for scanned_files.
        if not semgrep_ran and scanned_files is None:
            try:
                scanned_files = count_scanned_files(repo_path)
            except OSError:
                scanned_files = None

        # ---- Posture ----
        tools["posture"] = tools["posture"].model_copy(update={"state": "active"})
        await _emit_tool(on_tool, tools["posture"])
        await _emit_step(on_step, "posture")
        posture_started = time.perf_counter()
        posture_results = await run_all_posture_checks(
            repo_path,
            gh_client=gh_client,
            coords=coords,
            assessment_id=assessment_id,
        )
        durations_ms["posture"] = _elapsed_ms(posture_started)

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
    trivy_scope = _format_trivy_scope(scanned_deps, ecosystems)
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
            # IMPL-0009 — single Trivy invocation does both passes; honest copy.
            "ran": "Dependency + secret scan",
            "scope": trivy_scope,
            "duration_ms": durations_ms.get("trivy"),
        }
    )
    await _emit_tool(on_tool, tools["trivy"])

    if semgrep_ran and semgrep_result is not None:
        sg_count = len(semgrep_result.findings)
        sg_scope = _format_semgrep_scope(scanned_files)
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
                "ran": f"Static analysis ({SEMGREP_RULESETS_LABEL})",
                "scope": sg_scope,
                "duration_ms": durations_ms.get("semgrep"),
            }
        )
        await _emit_tool(on_tool, tools["semgrep"])

    posture_pass = sum(1 for pc in posture_results if pc.status == "pass")
    posture_total = len(posture_results)
    tools["posture"] = tools["posture"].model_copy(
        update={
            "state": "done",
            "version": POSTURE_CHECKER_VERSION,
            "result": AssessmentToolResult(
                kind="pass_count",
                value=posture_pass,
                text=f"{posture_pass} pass",
            ),
            "ran": f"{posture_total} repo + cloud configuration checks",
            "scope": _format_posture_scope(posture_total),
            "duration_ms": durations_ms.get("posture"),
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

    # IMPL-0009 — persist scope fields onto the Assessment row when DB is in
    # play. Routes that bypass the DB (test mode) still receive the values on
    # the returned ``AssessmentResult`` and can persist themselves.
    if db is not None:
        from cliff.db.dao.assessment import update_assessment
        from cliff.models.assessment import AssessmentUpdate

        await update_assessment(
            db,
            assessment_id,
            AssessmentUpdate(
                commit_sha=commit_sha,
                branch=resolved_branch,
                scanned_files=scanned_files,
                scanned_deps=scanned_deps,
            ),
        )

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
        commit_sha=commit_sha,
        branch=resolved_branch,
        scanned_files=scanned_files,
        scanned_deps=scanned_deps,
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
    from cliff.db.repo_finding import (
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


def _elapsed_ms(started: float) -> int:
    """Return milliseconds since ``time.perf_counter()`` reading ``started``."""
    return max(0, int((time.perf_counter() - started) * 1000))


def _format_trivy_scope(deps: int | None, ecosystems: list[str]) -> str:
    """Honest description of Trivy's combined dependency + secret pass."""
    parts: list[str] = []
    if deps is not None and deps > 0:
        parts.append(f"{deps} {'dep' if deps == 1 else 'deps'}")
    if ecosystems:
        parts.append(" + ".join(ecosystems))
    parts.append("git history")
    return " · ".join(parts)


def _format_semgrep_scope(files: int | None) -> str:
    if files is None:
        return SEMGREP_RULESETS_LABEL
    return (
        f"{files} {'file' if files == 1 else 'files'} · {SEMGREP_RULESETS_LABEL}"
    )


def _format_posture_scope(total: int) -> str:
    return f"{total} repo + cloud configuration checks"


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
    owner, repo = _owner_repo_from_url(repo_url)
    return RepoCoords(owner=owner, repo=repo, branch=branch)


def _owner_repo_from_url(repo_url: str) -> tuple[str, str]:
    """Parse ``(owner, repo)`` out of an HTTPS or SSH GitHub URL."""
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
    return owner, repo


async def _resolve_default_branch(
    gh_client: GithubAPI, owner: str, repo: str
) -> str:
    """Resolve the repo's real default branch via ``GET /repos/{owner}/{repo}``.

    Q01R-B23 — before this fix the posture engine hardcoded ``main`` for
    every probe, which 403'd on branch protection and 404'd on
    ``/commits?sha=main`` for every ``master``-default repo (NodeGoat and
    friends). Falls back to ``main`` when the client doesn't expose
    ``get_repo_info`` (older test fakes) or when the call returns
    :class:`UnableToVerify` (rate-limited / forbidden / network error) —
    the per-check probe will then degrade to ``unknown`` rather than
    aborting the whole run.
    """
    from cliff.assessment.posture.github_client import UnableToVerify

    getter = getattr(gh_client, "get_repo_info", None)
    if getter is None:
        return "main"
    info = await getter(owner, repo)
    if isinstance(info, UnableToVerify):
        # Operator-visible breadcrumb: when the fallback fires on a
        # master-default repo, every branch-scoped probe will degrade to
        # ``unknown`` — without this log line that's silent on the wire.
        logger.info(
            "default-branch lookup unavailable for %s/%s (%s); falling back to 'main'",
            owner,
            repo,
            info.reason,
        )
        return "main"
    if isinstance(info, dict):
        candidate = info.get("default_branch")
        if isinstance(candidate, str) and candidate:
            return candidate
    logger.info(
        "default-branch missing/invalid in repo info for %s/%s; falling back to 'main'",
        owner,
        repo,
    )
    return "main"


__all__ = [
    "RepoCloner",
    "_coords_from_repo_url",
    "derive_grade",
    "run_assessment",
]
