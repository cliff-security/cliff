"""Pydantic models for scanner outputs (Epic 1).

These shapes are deliberately scanner-agnostic at the consumer boundary —
:mod:`cliff.assessment.to_findings` (Epic 3b) maps them onto the unified
``finding`` table.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ScannerStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNVERIFIED = "unverified"  # binary present but checksum mismatched (warn mode)


class ScannerInfo(BaseModel):
    name: str
    version: str | None
    available: bool
    status: ScannerStatus = ScannerStatus.AVAILABLE
    detail: str | None = None


class TrivyVulnerability(BaseModel):
    pkg_name: str
    installed_version: str
    vuln_id: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN
    title: str
    primary_url: str | None = None
    fixed_version: str | None = None
    description: str | None = None


class TrivySecret(BaseModel):
    rule_id: str
    category: str
    severity: str
    title: str
    path: str
    start_line: int
    end_line: int | None = None
    match: str | None = None


class TrivyMisconfiguration(BaseModel):
    id: str
    title: str
    severity: str
    path: str
    description: str | None = None


class TrivyResult(BaseModel):
    version: str
    target: str
    vulnerabilities: list[TrivyVulnerability] = Field(default_factory=list)
    secrets: list[TrivySecret] = Field(default_factory=list)
    misconfigurations: list[TrivyMisconfiguration] = Field(default_factory=list)


class SemgrepFinding(BaseModel):
    check_id: str
    path: str
    start_line: int
    end_line: int
    severity: str  # ERROR | WARNING | INFO
    message: str
    cwe: list[str] = Field(default_factory=list)


class SemgrepResult(BaseModel):
    version: str
    findings: list[SemgrepFinding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
