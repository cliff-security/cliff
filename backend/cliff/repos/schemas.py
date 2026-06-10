"""Project-profile artifact schemas (ADR-0053 §3).

The typed shapes the profile builders emit and the triage Deep dive (ADR-0052)
consumes. ``extra="allow"`` keeps them forward-compatible (a newer builder can
add a field without breaking an older reader); a breaking change bumps
``RepoDirManager.SCHEMA_VERSION`` and the artifact is rebuilt, not migrated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ── Profile the project ──────────────────────────────────────────────────────

RepoKind = Literal["library", "service", "cli", "self_hosted_app", "monolith", "unknown"]


class EntryPoint(BaseModel):
    model_config = {"extra": "allow"}
    kind: str  # http | cli | queue | deserializer | webhook | ...
    location: str | None = None  # file:line
    description: str | None = None


class RepoProfile(BaseModel):
    """``profile.json`` — what the project is and how it runs."""

    model_config = {"extra": "allow"}
    kind: RepoKind = "unknown"
    deployment: str | None = None
    internet_facing: bool | None = None  # tri-state: None = couldn't determine
    entry_points: list[EntryPoint] = []
    trust_boundary: str | None = None
    build_cmd: str | None = None
    run_cmd: str | None = None
    docker_present: bool = False
    dockerfile_path: str | None = None
    summary: str | None = None  # one plain-English paragraph for PROFILE.md


# ── Map the live code ────────────────────────────────────────────────────────

PathCategory = Literal[
    "ships", "test", "fixture", "example", "docs", "build", "vendored", "dead"
]


class PathClass(BaseModel):
    model_config = {"extra": "allow"}
    glob: str
    category: PathCategory
    reason: str | None = None


class CodeMap(BaseModel):
    """``code_map.json`` — what ships vs what doesn't."""

    model_config = {"extra": "allow"}
    ships_roots: list[str] = []
    excluded_roots: list[str] = []
    classified: list[PathClass] = []


# ── Review past issues ───────────────────────────────────────────────────────

FixCoverage = Literal["instance", "class", "none"]


class PriorIssue(BaseModel):
    model_config = {"extra": "allow"}
    id: str  # CVE / GHSA id
    root_cause_family: str | None = None
    fixed: FixCoverage | None = None
    summary: str | None = None


class ThreatHistory(BaseModel):
    """``threat.json`` — the repo's prior vulnerabilities and recurring weak spots."""

    model_config = {"extra": "allow"}
    prior_issues: list[PriorIssue] = []
    recurring_families: list[str] = []
    fertile_areas: list[str] = []
