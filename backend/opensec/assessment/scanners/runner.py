"""Subprocess-only scanner runner (ADR-0028).

The runner is the single point at which OpenSec hands control to a third-party
scanner binary. Two security guarantees live here:

1. **Env whitelist.** The subprocess inherits only ``PATH``, ``HOME``, ``LANG``,
   ``TRIVY_CACHE_DIR``, and ``SEMGREP_RULES_CACHE_DIR`` from the parent. Most
   importantly ``GITHUB_PAT`` cannot reach the scanner — a compromised binary
   should not be able to exfiltrate the user's GitHub token.
2. **Process-group teardown.** Trivy and Semgrep both spawn helpers; killing
   only the top-level pid leaves orphans. We use ``start_new_session=True`` so
   the runner can ``os.killpg(SIGKILL)`` on timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

from opensec.assessment._fs import SKIP_DIRS
from opensec.assessment.scanners.models import (
    ScannerInfo,
    ScannerStatus,
    SemgrepFinding,
    SemgrepResult,
    TrivyMisconfiguration,
    TrivyResult,
    TrivySecret,
    TrivyVulnerability,
)

logger = logging.getLogger(__name__)

#: Allowed environment variables for scanner subprocesses (ADR-0028).
SCANNER_ENV_ALLOW: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "TRIVY_CACHE_DIR",
    "SEMGREP_RULES_CACHE_DIR",
)


class ScannerTimeoutError(RuntimeError):
    """Raised when a scanner subprocess exceeds its timeout budget."""


@dataclass(frozen=True)
class _ProcResult:
    returncode: int
    stdout: str
    stderr: str


class ScannerRunner(Protocol):
    """Protocol the assessment engine consumes."""

    async def run_trivy(self, target_dir: Path, *, timeout: float) -> TrivyResult: ...
    async def run_semgrep(self, target_dir: Path, *, timeout: float) -> SemgrepResult: ...
    def available_scanners(self) -> list[ScannerInfo]: ...


def _scanner_env() -> dict[str, str]:
    """Return the whitelisted env subset (ADR-0028)."""
    return {k: os.environ[k] for k in SCANNER_ENV_ALLOW if k in os.environ}


_TRIVY_VERSION_RE = re.compile(r"Version:\s*([0-9][0-9A-Za-z.\-+]*)")
_SEMGREP_VERSION_RE = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)")


def _skip_dirs_csv() -> str:
    """Comma-separated SKIP_DIRS globs for ``trivy --skip-dirs``.

    Trivy walks the target directory itself, so the in-process
    :func:`opensec.assessment._fs.iter_repo_files` exclusion has no effect on
    it. Without this we report hundreds of false-positive CVEs from
    intentionally-vulnerable lockfiles under ``backend/tests/fixtures/`` and
    similar test-data directories — including on the OpenSec repo itself.

    Trivy uses doublestar globs against paths relative to the scan target, so
    matching a directory at any depth requires ``**/<name>``. A bare
    basename only matches at the scan root and silently misses nested
    occurrences (the OpenSec case).
    """
    return ",".join(f"**/{d}" for d in sorted(SKIP_DIRS))


def _semgrep_exclude_args() -> list[str]:
    """``--exclude`` flags for Semgrep matching :data:`SKIP_DIRS`.

    Semgrep takes one ``--exclude PATTERN`` per directory and applies it to
    each path segment, so a basename like ``fixtures`` is enough — no glob
    prefix needed.
    """
    args: list[str] = []
    for d in sorted(SKIP_DIRS):
        args.extend(("--exclude", d))
    return args


class SubprocessScannerRunner:
    """Default :class:`ScannerRunner` — invokes pinned binaries via subprocess."""

    def __init__(self, *, bin_dir: Path) -> None:
        self._bin_dir = Path(bin_dir)

    # ------------------------------------------------------------------ helpers
    def _binary(self, name: str) -> Path:
        return self._bin_dir / name

    async def _run_subprocess(
        self,
        cmd: Sequence[str],
        *,
        timeout: float,
        cwd: Path | None = None,
    ) -> _ProcResult:
        """Spawn ``cmd`` with the whitelisted env and a timeout-driven kill.

        Returned object exposes ``returncode`` / ``stdout`` / ``stderr`` even on
        non-zero exits; only :class:`ScannerTimeoutError` is raised, never a
        ``CalledProcessError``-style exception, so callers can decide how to
        treat partial output.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_scanner_env(),
            cwd=str(cwd) if cwd else None,
            start_new_session=True,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            if proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            await proc.wait()
            raise ScannerTimeoutError(
                f"scanner subprocess timed out after {timeout}s: {cmd[0]}"
            ) from None
        return _ProcResult(
            returncode=proc.returncode or 0,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )

    # ------------------------------------------------------------- introspection
    def available_scanners(self) -> list[ScannerInfo]:
        infos: list[ScannerInfo] = []
        for name in ("trivy", "semgrep"):
            path = self._binary(name)
            if path.exists() and os.access(path, os.X_OK):
                infos.append(
                    ScannerInfo(name=name, version=None, available=True)
                )
            else:
                infos.append(
                    ScannerInfo(
                        name=name,
                        version=None,
                        available=False,
                        status=ScannerStatus.MISSING,
                        detail=f"{path} not found",
                    )
                )
        return infos

    async def _binary_version(self, name: str, *, regex: re.Pattern[str]) -> str:
        try:
            proc = await self._run_subprocess(
                [str(self._binary(name)), "--version"], timeout=5
            )
        except ScannerTimeoutError:
            return "unknown"
        match = regex.search(proc.stdout) or regex.search(proc.stderr)
        return match.group(1) if match else "unknown"

    # ------------------------------------------------------------- run helpers
    async def run_trivy(self, target_dir: Path, *, timeout: float) -> TrivyResult:
        version = await self._binary_version("trivy", regex=_TRIVY_VERSION_RE)
        proc = await self._run_subprocess(
            [
                str(self._binary("trivy")),
                "fs",
                "--format",
                "json",
                "--scanners",
                "vuln,secret,misconfig",
                "--skip-dirs",
                _skip_dirs_csv(),
                str(target_dir),
            ],
            timeout=timeout,
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(
                f"trivy fs failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        return _parse_trivy(proc.stdout, version=version, target=str(target_dir))

    async def run_semgrep(self, target_dir: Path, *, timeout: float) -> SemgrepResult:
        version = await self._binary_version("semgrep", regex=_SEMGREP_VERSION_RE)
        proc = await self._run_subprocess(
            [
                str(self._binary("semgrep")),
                "--config",
                "p/security-audit",
                "--json",
                "--quiet",
                *_semgrep_exclude_args(),
                str(target_dir),
            ],
            timeout=timeout,
        )
        if proc.returncode not in (0, 1) and not proc.stdout.strip():
            # Semgrep exit codes: 0 = no findings, 1 = findings present. Anything
            # else with no JSON body is a real failure.
            raise RuntimeError(
                f"semgrep failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        return _parse_semgrep(proc.stdout, version=version)


# ---------------------------------------------------------------- JSON parsing
_SEVERITY_NORMALIZE = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "UNKNOWN": "UNKNOWN",
}


def _parse_trivy(raw: str, *, version: str, target: str) -> TrivyResult:
    payload = json.loads(raw or "{}")
    vulns: list[TrivyVulnerability] = []
    secrets: list[TrivySecret] = []
    misconfigs: list[TrivyMisconfiguration] = []
    for result in payload.get("Results", []) or []:
        result_target = result.get("Target") or target
        for v in result.get("Vulnerabilities", []) or []:
            vulns.append(
                TrivyVulnerability(
                    pkg_name=v.get("PkgName", ""),
                    installed_version=v.get("InstalledVersion", ""),
                    vuln_id=v.get("VulnerabilityID", ""),
                    severity=_SEVERITY_NORMALIZE.get(
                        (v.get("Severity") or "").upper(), "UNKNOWN"
                    ),
                    title=v.get("Title") or v.get("VulnerabilityID", ""),
                    primary_url=v.get("PrimaryURL"),
                    fixed_version=v.get("FixedVersion"),
                    description=v.get("Description"),
                )
            )
        for s in result.get("Secrets", []) or []:
            secrets.append(
                TrivySecret(
                    rule_id=s.get("RuleID", ""),
                    category=s.get("Category", ""),
                    severity=_SEVERITY_NORMALIZE.get(
                        (s.get("Severity") or "").upper(), "UNKNOWN"
                    ),
                    title=s.get("Title") or s.get("RuleID", ""),
                    path=result_target,
                    start_line=int(s.get("StartLine") or 0),
                    end_line=s.get("EndLine"),
                    match=s.get("Match"),
                )
            )
        for m in result.get("Misconfigurations", []) or []:
            misconfigs.append(
                TrivyMisconfiguration(
                    id=m.get("ID", ""),
                    title=m.get("Title", ""),
                    severity=_SEVERITY_NORMALIZE.get(
                        (m.get("Severity") or "").upper(), "UNKNOWN"
                    ),
                    path=result_target,
                    description=m.get("Description"),
                )
            )
    return TrivyResult(
        version=version,
        target=target,
        vulnerabilities=vulns,
        secrets=secrets,
        misconfigurations=misconfigs,
    )


def _parse_semgrep(raw: str, *, version: str) -> SemgrepResult:
    payload = json.loads(raw or "{}")
    findings: list[SemgrepFinding] = []
    for r in payload.get("results", []) or []:
        start = r.get("start") or {}
        end = r.get("end") or {}
        extra = r.get("extra") or {}
        meta = extra.get("metadata") or {}
        cwe = meta.get("cwe") or []
        if isinstance(cwe, str):
            cwe = [cwe]
        findings.append(
            SemgrepFinding(
                check_id=r.get("check_id", ""),
                path=r.get("path", ""),
                start_line=int(start.get("line") or 0),
                end_line=int(end.get("line") or start.get("line") or 0),
                severity=(extra.get("severity") or "INFO").upper(),
                message=extra.get("message", ""),
                cwe=list(cwe),
            )
        )
    errors = [str(e.get("message", e)) for e in (payload.get("errors") or [])]
    sg_version = payload.get("version") or version
    return SemgrepResult(version=str(sg_version), findings=findings, errors=errors)
