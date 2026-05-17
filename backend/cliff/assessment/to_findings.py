"""Deterministic scanner-result -> FindingCreate mappers (ADR-0027 §6).

Every internal producer (Trivy vulns, Trivy secrets, Semgrep, posture)
converges on a list of :class:`FindingCreate` rows that the unified UPSERT
in :mod:`cliff.db.repo_finding` persists. The mappers are pure: no I/O,
no DB writes, no LLM. The four functions here form the only Phase-2-internal
producer set; external scanner payloads (Snyk, Wiz, CSV uploads) still go
through the LLM normalizer in :mod:`cliff.integrations.normalizer` which
emits ``FindingCreate`` rows in the same shape.

Source-id conventions (verbatim from IMPL-0003-p2 §"Source-id conventions"):

    dependency  ``{PkgName}@{InstalledVersion}:{VulnID}``
    secret      ``{path}:{startLine}:{RuleID}``
    code        ``{path}:{startLine}:{check_id}``
    posture     ``{repo_url}:{check_name}``

These are stable across scans so the UPSERT on ``(source_type, source_id)``
finds the same row each time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.assessment.posture import (
    ADVISORY_CHECKS,
    CHECK_CATEGORY,
    CHECK_DESCRIPTION,
    CHECK_DISPLAY_NAME,
    CHECK_SEVERITY,
)
from cliff.models.finding import FindingCreate

if TYPE_CHECKING:
    from cliff.assessment.posture import PostureCheckResult
    from cliff.assessment.scanners.models import (
        SemgrepResult,
        TrivyResult,
    )

# Deterministic severity → normalized_priority. The dashboard groups
# findings by ``normalized_priority`` so this maps every scanner's vocabulary
# onto the four-bucket scale.
_PRIORITY_BY_SEVERITY: dict[str, str] = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MODERATE": "medium",
    "MEDIUM": "medium",
    "LOW": "low",
    "WARNING": "medium",
    "ERROR": "high",
    "INFO": "low",
}


def _priority(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    return _PRIORITY_BY_SEVERITY.get(raw.upper())


# --------------------------------------------------------------------- Trivy vulns


def from_trivy_vulns(
    result: TrivyResult, *, assessment_id: str
) -> list[FindingCreate]:
    """Trivy vulnerability rows → ``type='dependency'``, ``source_type='trivy'``."""
    out: list[FindingCreate] = []
    for v in result.vulnerabilities:
        out.append(
            FindingCreate(
                source_type="trivy",
                source_id=f"{v.pkg_name}@{v.installed_version}:{v.vuln_id}",
                type="dependency",
                grade_impact="counts",
                assessment_id=assessment_id,
                title=v.title or v.vuln_id,
                description=v.description,
                raw_severity=v.severity,
                normalized_priority=_priority(v.severity),
                asset_label=f"{v.pkg_name}@{v.installed_version}",
                raw_payload={
                    "vuln_id": v.vuln_id,
                    "package": v.pkg_name,
                    "version": v.installed_version,
                    "fixed_version": v.fixed_version,
                    "primary_url": v.primary_url,
                },
            )
        )
    return out


# --------------------------------------------------------------------- Trivy secrets


def from_trivy_secrets(
    result: TrivyResult, *, assessment_id: str
) -> list[FindingCreate]:
    """Trivy secret rows → ``type='secret'``, ``source_type='trivy-secret'``."""
    out: list[FindingCreate] = []
    for s in result.secrets:
        out.append(
            FindingCreate(
                source_type="trivy-secret",
                source_id=f"{s.path}:{s.start_line}:{s.rule_id}",
                type="secret",
                grade_impact="counts",
                assessment_id=assessment_id,
                title=s.title or s.rule_id,
                description=s.match,
                raw_severity=s.severity,
                normalized_priority=_priority(s.severity),
                asset_label=s.path,
                raw_payload={
                    "rule_id": s.rule_id,
                    "category": s.category,
                    "path": s.path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                },
            )
        )
    return out


# --------------------------------------------------------------------- Semgrep


def from_semgrep(
    result: SemgrepResult, *, assessment_id: str
) -> list[FindingCreate]:
    """Semgrep rows → ``type='code'``, ``source_type='semgrep'``."""
    out: list[FindingCreate] = []
    for f in result.findings:
        out.append(
            FindingCreate(
                source_type="semgrep",
                source_id=f"{f.path}:{f.start_line}:{f.check_id}",
                type="code",
                grade_impact="counts",
                assessment_id=assessment_id,
                title=f.message or f.check_id,
                description=f.message,
                raw_severity=f.severity,
                normalized_priority=_priority(f.severity),
                asset_label=f.path,
                raw_payload={
                    "check_id": f.check_id,
                    "path": f.path,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "cwe": f.cwe,
                },
            )
        )
    return out


# --------------------------------------------------------------------- Posture


def from_posture(
    results: list[PostureCheckResult],
    *,
    repo_url: str,
    assessment_id: str,
) -> list[FindingCreate]:
    """Posture results → ``type='posture'``, ``source_type='cliff-posture'``.

    Per CEO directive (2026-04-26), every check (``pass`` / ``fail`` / ``advisory``)
    becomes a finding row; only ``unknown`` is skipped because absence of signal
    is not evidence of fix (ADR-0027 §7). The mapper sets ``status`` per the
    type-conditional preservation rule:

        scanner ``pass`` → status='passed', grade_impact='counts'
        scanner ``fail`` → status='new',    grade_impact='counts'
        advisory check  → status='new',    grade_impact='advisory'

    Subsequent UPSERTs refresh ``status`` for posture rows (the scanner is the
    source of truth for "is this check currently passing?"); user-set fields
    on non-posture types remain preserved per the table in IMPL-0003-p2.
    """
    out: list[FindingCreate] = []
    for r in results:
        if r.status == "unknown":
            continue
        is_advisory = r.check_name in ADVISORY_CHECKS or r.status == "advisory"
        # Branch on the scanner verdict even within advisory: an advisory
        # check that *passed* is not an action item — it should land as
        # ``passed``, not ``new``. Without this, passing advisories
        # (e.g. signed_commits 20/20, workflow_trigger_scope flagged_count=0)
        # show up on the Issues page indistinguishable from real failures.
        if is_advisory:
            grade_impact = "advisory"
            status = "passed" if r.status == "pass" else "new"
        elif r.status == "pass":
            grade_impact = "counts"
            status = "passed"
        else:
            grade_impact = "counts"
            status = "new"

        category = CHECK_CATEGORY.get(r.check_name, "repo_configuration")
        severity = CHECK_SEVERITY.get(r.check_name, "medium")
        out.append(
            FindingCreate(
                source_type="cliff",
                source_id=f"{repo_url}:{r.check_name}",
                type="posture",
                grade_impact=grade_impact,
                assessment_id=assessment_id,
                category=category,
                status=status,
                title=CHECK_DISPLAY_NAME.get(r.check_name, r.check_name),
                description=CHECK_DESCRIPTION.get(r.check_name),
                raw_severity=severity,
                normalized_priority=severity,
                asset_label=repo_url,
                raw_payload={
                    "check_name": r.check_name,
                    "scanner_status": r.status,
                    "detail": r.detail,
                },
            )
        )
    return out


__all__ = ["from_posture", "from_semgrep", "from_trivy_secrets", "from_trivy_vulns"]
