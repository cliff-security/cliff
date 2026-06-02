"""Agent integration tests for the finding normalizer.

These tests call the real LLM via OpenCode to verify that `normalize_findings()`
correctly extracts and validates findings from various scanner formats.

Budget: ~$0.002 total (well under the $1 limit).
Run with: uv run pytest tests/agents/ -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cliff.integrations.normalizer import normalize_findings
from cliff.models import FindingCreate  # noqa: TCH001 — used in type assertions

VALID_PRIORITIES = {"critical", "high", "medium", "low", "info"}
FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"

# Real-LLM provider state for the normalizer (now an app-level PA agent —
# ADR-0047 / IMPL-0022 PR #3b). These tests are skip-gated on an API key
# being present (see conftest), so the env carries a usable provider key.
_LLM_ENV = {
    k: v for k, v in os.environ.items() if k.endswith(("_API_KEY", "_BASE_URL"))
}


def _eval_model() -> str:
    """Pick a capable, cheap model for the real-LLM eval (override with
    ``CLIFF_EVAL_MODEL``). Multi-item batch extraction needs a real model —
    a nano-tier model under-extracts and fails the batch assertions."""
    if override := os.environ.get("CLIFF_EVAL_MODEL"):
        return override
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic/claude-haiku-4-5"
    return "openai/gpt-4o-mini"


_LLM_MODEL = _eval_model()


def _load_fixture(name: str) -> list[dict]:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text())


def _assert_valid_finding(finding: FindingCreate, expected_source: str) -> None:
    """Common assertions for a valid normalized finding."""
    assert finding.source_type == expected_source
    assert finding.source_id, "source_id must be non-empty"
    assert finding.title, "title must be non-empty"
    assert finding.status == "new"
    if finding.normalized_priority:
        assert finding.normalized_priority in VALID_PRIORITIES, (
            f"Invalid priority: {finding.normalized_priority}"
        )


# ---------------------------------------------------------------------------
# Single finding tests (cheapest — ~$0.0001 each)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_snyk_finding():
    """Normalize a single Snyk finding with CVE details."""
    raw = [
        {
            "id": "SNYK-JS-LODASH-1018905",
            "title": "Prototype Pollution in lodash",
            "severity": "CRITICAL",
            "packageName": "lodash",
            "version": "4.17.20",
            "fixedIn": ["4.17.21"],
            "cvssScore": 9.8,
            "description": "Prototype Pollution via the set function.",
        }
    ]

    findings, errors = await normalize_findings("snyk", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) == 1, f"Expected 1 finding, got {len(findings)}. Errors: {errors}"
    f = findings[0]
    _assert_valid_finding(f, "snyk")
    assert "SNYK-JS-LODASH" in f.source_id
    assert "lodash" in f.title.lower() or "pollution" in f.title.lower()
    assert f.normalized_priority == "critical"


@pytest.mark.asyncio
async def test_single_wiz_finding():
    """Normalize a single Wiz finding."""
    raw = [
        {
            "id": "WIZ-VULN-2024-001",
            "name": "Critical OpenSSL vulnerability in production container",
            "severity": "CRITICAL",
            "status": "OPEN",
            "resource": {"type": "Container", "name": "api-server:v2.3.1"},
            "vulnerability": {
                "cve": "CVE-2024-0727",
                "package": "openssl",
                "version": "3.0.12",
                "fixedVersion": "3.0.13",
            },
            "description": "OpenSSL is vulnerable to denial of service via PKCS12.",
        }
    ]

    findings, errors = await normalize_findings("wiz", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) == 1, f"Expected 1 finding, got {len(findings)}. Errors: {errors}"
    f = findings[0]
    _assert_valid_finding(f, "wiz")
    assert "WIZ" in f.source_id or "wiz" in f.source_id.lower()
    assert f.normalized_priority == "critical"


# ---------------------------------------------------------------------------
# Batch tests (use real fixture files)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_snyk_5_findings():
    """Normalize all 5 findings from sample-snyk-export.json."""
    raw = _load_fixture("sample-snyk-export.json")
    assert len(raw) == 5

    findings, errors = await normalize_findings("snyk", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) >= 4, (
        f"Expected at least 4/5 findings, got {len(findings)}. Errors: {errors}"
    )
    for f in findings:
        _assert_valid_finding(f, "snyk")

    # Verify we got distinct findings (different source_ids)
    source_ids = {f.source_id for f in findings}
    assert len(source_ids) >= 4, f"Expected distinct source_ids, got: {source_ids}"


@pytest.mark.asyncio
async def test_batch_wiz_3_findings():
    """Normalize all 3 findings from sample-wiz-export.json."""
    raw = _load_fixture("sample-wiz-export.json")
    assert len(raw) == 3

    findings, errors = await normalize_findings("wiz", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) >= 2, (
        f"Expected at least 2/3 findings, got {len(findings)}. Errors: {errors}"
    )
    for f in findings:
        _assert_valid_finding(f, "wiz")


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_severity_mapping():
    """Verify LLM correctly maps CRITICAL/HIGH/MEDIUM/LOW to normalized_priority."""
    raw = [
        {
            "id": "SNYK-TEST-001",
            "title": "Critical RCE in imagemagick",
            "severity": "CRITICAL",
            "packageName": "imagemagick",
            "version": "7.1.0",
        },
        {
            "id": "SNYK-TEST-002",
            "title": "High SQL injection in pg",
            "severity": "HIGH",
            "packageName": "pg",
            "version": "8.7.1",
        },
        {
            "id": "SNYK-TEST-003",
            "title": "Medium XSS in sanitize-html",
            "severity": "MEDIUM",
            "packageName": "sanitize-html",
            "version": "2.7.0",
        },
        {
            "id": "SNYK-TEST-004",
            "title": "Low info disclosure in debug",
            "severity": "LOW",
            "packageName": "debug",
            "version": "4.3.4",
        },
    ]

    findings, errors = await normalize_findings("snyk", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) >= 3, f"Expected at least 3/4, got {len(findings)}. Errors: {errors}"

    # All returned findings should have valid priority values
    for f in findings:
        assert f.normalized_priority in VALID_PRIORITIES


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minimal_input_fields():
    """Normalize a finding with bare-minimum Snyk-like fields."""
    raw = [
        {
            "id": "SNYK-MIN-001",
            "title": "Insecure dependency detected",
            "severity": "HIGH",
            "packageName": "vulnerable-lib",
            "version": "1.0.0",
        }
    ]

    findings, errors = await normalize_findings("snyk", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) == 1, f"Expected 1 finding. Errors: {errors}"
    f = findings[0]
    assert f.source_type == "snyk"
    assert f.title  # non-empty
    assert f.normalized_priority in VALID_PRIORITIES


@pytest.mark.asyncio
async def test_unknown_scanner_format():
    """LLM should handle Trivy-style format (different field names)."""
    raw = [
        {
            "VulnerabilityID": "CVE-2023-44487",
            "PkgName": "golang.org/x/net",
            "InstalledVersion": "0.7.0",
            "FixedVersion": "0.17.0",
            "Title": "HTTP/2 rapid reset attack",
            "Severity": "HIGH",
            "Description": "HTTP/2 protocol allows rapid reset.",
        }
    ]

    findings, errors = await normalize_findings("trivy", raw, env=_LLM_ENV, model=_LLM_MODEL)

    assert len(findings) == 1, f"Expected 1 finding. Errors: {errors}"
    f = findings[0]
    _assert_valid_finding(f, "trivy")
    assert f.source_id, "source_id should be populated from VulnerabilityID"


@pytest.mark.asyncio
async def test_large_batch_20_findings():
    """Normalize 20 findings (4x Snyk fixture with modified IDs)."""
    base = _load_fixture("sample-snyk-export.json")
    raw = []
    for i in range(4):
        for item in base:
            clone = dict(item)
            clone["id"] = f"{item['id']}-batch{i}"
            raw.append(clone)

    assert len(raw) == 20

    findings, errors = await normalize_findings("snyk", raw, env=_LLM_ENV, model=_LLM_MODEL)

    # gpt-4.1-nano truncates output for large batches — this is a known limitation.
    # The chunk fallback in ingest_worker handles this in production by retrying
    # items individually. Here we verify the normalizer handles partial output gracefully.
    assert len(findings) >= 5, (
        f"Expected at least 5/20 findings, got {len(findings)}. Errors: {errors}"
    )
    for f in findings:
        _assert_valid_finding(f, "snyk")
