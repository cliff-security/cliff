"""Pydantic shape contracts for scanner result models (Epic 1)."""

from __future__ import annotations

from cliff.assessment.scanners.models import (
    ScannerInfo,
    ScannerStatus,
    SemgrepFinding,
    SemgrepResult,
    TrivyResult,
    TrivySecret,
    TrivyVulnerability,
)


def test_scanner_info_defaults() -> None:
    info = ScannerInfo(name="trivy", version="0.52.0", available=True)
    assert info.name == "trivy"
    assert info.available is True
    assert info.status == ScannerStatus.AVAILABLE


def test_scanner_info_unavailable_carries_reason() -> None:
    info = ScannerInfo(
        name="semgrep",
        version=None,
        available=False,
        status=ScannerStatus.MISSING,
        detail="bin/semgrep not found",
    )
    assert info.available is False
    assert info.status == ScannerStatus.MISSING
    assert "not found" in (info.detail or "")


def test_trivy_vulnerability_required_fields() -> None:
    v = TrivyVulnerability(
        pkg_name="lodash",
        installed_version="4.17.19",
        vuln_id="CVE-2021-23337",
        severity="HIGH",
        title="Command injection in lodash",
        primary_url="https://nvd.nist.gov/vuln/detail/CVE-2021-23337",
    )
    assert v.severity == "HIGH"
    assert v.pkg_name == "lodash"


def test_trivy_secret_required_fields() -> None:
    s = TrivySecret(
        rule_id="aws-access-key-id",
        category="AWS",
        severity="CRITICAL",
        title="AWS Access Key ID",
        path="src/config.js",
        start_line=42,
    )
    assert s.path.endswith("config.js")
    assert s.start_line == 42


def test_trivy_result_groups_vulns_and_secrets() -> None:
    result = TrivyResult(
        version="0.52.0",
        target="/tmp/repo",
        vulnerabilities=[],
        secrets=[],
        misconfigurations=[],
    )
    assert result.version == "0.52.0"
    assert result.vulnerabilities == []


def test_semgrep_result_groups_findings() -> None:
    finding = SemgrepFinding(
        check_id="python.django.security.audit.sqli",
        path="app/db.py",
        start_line=88,
        end_line=88,
        severity="ERROR",
        message="Potential SQL injection",
    )
    result = SemgrepResult(version="1.70.0", findings=[finding])
    assert result.findings[0].check_id.startswith("python.django")
    assert result.version == "1.70.0"
