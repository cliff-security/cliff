"""Mapper tests for ``to_findings.py`` (IMPL-0003-p2 Phase 2).

Round-trips Trivy vuln / Trivy secret / Semgrep / posture inputs through the
deterministic mappers, asserts the source-id format and the type/grade_impact
taxonomy from ADR-0027.
"""

from __future__ import annotations

from opensec.assessment.posture import CHECK_DISPLAY_NAME, PostureCheckResult
from opensec.assessment.scanners.models import (
    SemgrepFinding,
    SemgrepResult,
    TrivyResult,
    TrivySecret,
    TrivyVulnerability,
)
from opensec.assessment.to_findings import (
    from_posture,
    from_semgrep,
    from_trivy_secrets,
    from_trivy_vulns,
)

REPO_URL = "https://github.com/acme/demo"
ASSESSMENT_ID = "asm-1"


# --------------------------------------------------------------------- Trivy vulns


def test_from_trivy_vulns_round_trip_fixture() -> None:
    result = TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        vulnerabilities=[
            TrivyVulnerability(
                pkg_name="lodash",
                installed_version="4.17.19",
                vuln_id="CVE-2021-23337",
                severity="HIGH",
                title="Command injection in lodash",
                fixed_version="4.17.21",
            )
        ],
    )
    findings = from_trivy_vulns(result, assessment_id=ASSESSMENT_ID)
    assert len(findings) == 1
    f = findings[0]
    assert f.source_type == "trivy"
    assert f.type == "dependency"
    assert f.grade_impact == "counts"
    assert f.assessment_id == ASSESSMENT_ID
    assert f.normalized_priority == "high"
    assert f.asset_label == "lodash@4.17.19"


def test_from_trivy_vulns_source_id_format() -> None:
    result = TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        vulnerabilities=[
            TrivyVulnerability(
                pkg_name="braces",
                installed_version="3.0.2",
                vuln_id="GHSA-grv7-fg5c-xmjg",
                severity="HIGH",
                title="ReDoS in braces",
            )
        ],
    )
    [f] = from_trivy_vulns(result, assessment_id=ASSESSMENT_ID)
    assert f.source_id == "braces@3.0.2:GHSA-grv7-fg5c-xmjg"


# --------------------------------------------------------------------- Trivy secrets


def test_from_trivy_secrets_round_trip_fixture() -> None:
    result = TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        secrets=[
            TrivySecret(
                rule_id="aws-access-key-id",
                category="AWS",
                severity="CRITICAL",
                title="AWS Access Key ID",
                path="src/config.js",
                start_line=42,
            )
        ],
    )
    [f] = from_trivy_secrets(result, assessment_id=ASSESSMENT_ID)
    assert f.source_type == "trivy-secret"
    assert f.type == "secret"
    assert f.grade_impact == "counts"
    assert f.normalized_priority == "critical"


def test_from_trivy_secrets_source_id_format() -> None:
    result = TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        secrets=[
            TrivySecret(
                rule_id="aws-access-key-id",
                category="AWS",
                severity="CRITICAL",
                title="AWS Access Key ID",
                path="src/config.js",
                start_line=42,
            )
        ],
    )
    [f] = from_trivy_secrets(result, assessment_id=ASSESSMENT_ID)
    assert f.source_id == "src/config.js:42:aws-access-key-id"


# --------------------------------------------------------------------- Semgrep


def test_from_semgrep_round_trip_fixture() -> None:
    result = SemgrepResult(
        version="1.70.0",
        findings=[
            SemgrepFinding(
                check_id="python.django.security.audit.sqli",
                path="app/db.py",
                start_line=88,
                end_line=88,
                severity="ERROR",
                message="Potential SQL injection",
                cwe=["CWE-89"],
            )
        ],
    )
    [f] = from_semgrep(result, assessment_id=ASSESSMENT_ID)
    assert f.source_type == "semgrep"
    assert f.type == "code"
    assert f.grade_impact == "counts"
    assert f.normalized_priority == "high"


def test_from_semgrep_source_id_format() -> None:
    result = SemgrepResult(
        version="1.70.0",
        findings=[
            SemgrepFinding(
                check_id="python.django.security.audit.sqli",
                path="app/db.py",
                start_line=88,
                end_line=88,
                severity="ERROR",
                message="Potential SQL injection",
            )
        ],
    )
    [f] = from_semgrep(result, assessment_id=ASSESSMENT_ID)
    assert f.source_id == "app/db.py:88:python.django.security.audit.sqli"


# --------------------------------------------------------------------- Posture


def test_from_posture_emits_all_fifteen_results_including_passes() -> None:
    """Per CEO direction (2026-04-26): pass + fail + advisory all become rows."""
    results = [
        PostureCheckResult(check_name="branch_protection", status="pass"),
        PostureCheckResult(check_name="security_md", status="fail"),
        PostureCheckResult(check_name="signed_commits", status="advisory"),
    ]
    findings = from_posture(
        results, repo_url=REPO_URL, assessment_id=ASSESSMENT_ID
    )
    assert len(findings) == 3
    by_status = {
        f.raw_payload["check_name"]: f.status for f in findings  # type: ignore[index]
    }
    assert by_status["branch_protection"] == "passed"
    assert by_status["security_md"] == "new"
    assert by_status["signed_commits"] == "new"


def test_from_posture_skips_unknown_status() -> None:
    """``unknown`` is absence-of-signal — never a finding row (ADR-0027 §7)."""
    results = [
        PostureCheckResult(check_name="branch_protection", status="unknown"),
        PostureCheckResult(check_name="security_md", status="pass"),
    ]
    findings = from_posture(
        results, repo_url=REPO_URL, assessment_id=ASSESSMENT_ID
    )
    assert len(findings) == 1
    assert findings[0].title == CHECK_DISPLAY_NAME["security_md"]
    assert findings[0].raw_payload["check_name"] == "security_md"  # type: ignore[index]


def test_from_posture_source_id_uses_repo_url_check_name() -> None:
    [f] = from_posture(
        [PostureCheckResult(check_name="branch_protection", status="pass")],
        repo_url=REPO_URL,
        assessment_id=ASSESSMENT_ID,
    )
    assert f.source_id == f"{REPO_URL}:branch_protection"


def test_from_posture_grade_impact_advisory_for_advisory_checks() -> None:
    """Advisory-by-name checks emit ``grade_impact='advisory'`` even on pass."""
    results = [
        PostureCheckResult(check_name="signed_commits", status="pass"),
        PostureCheckResult(check_name="workflow_trigger_scope", status="fail"),
        PostureCheckResult(check_name="broad_team_permissions", status="advisory"),
        PostureCheckResult(check_name="branch_protection", status="pass"),
    ]
    findings = from_posture(
        results, repo_url=REPO_URL, assessment_id=ASSESSMENT_ID
    )
    by_name = {f.raw_payload["check_name"]: f for f in findings}  # type: ignore[index]
    assert by_name["signed_commits"].grade_impact == "advisory"
    assert by_name["workflow_trigger_scope"].grade_impact == "advisory"
    assert by_name["broad_team_permissions"].grade_impact == "advisory"
    assert by_name["branch_protection"].grade_impact == "counts"


def test_from_posture_category_threaded_through() -> None:
    [f] = from_posture(
        [PostureCheckResult(check_name="actions_pinned_to_sha", status="pass")],
        repo_url=REPO_URL,
        assessment_id=ASSESSMENT_ID,
    )
    assert f.category == "ci_supply_chain"
