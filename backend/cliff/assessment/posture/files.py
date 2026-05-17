"""Filesystem posture checks: SECURITY.md, lockfile presence, dependabot.yml.

The lockfile check is name-based only — Trivy now owns dependency parsing
(ADR-0028), so we no longer need the ecosystem-specific parsers from PRD-0002
to answer "does this repo have any lockfile". A glob over a known list of
filenames is sufficient and keeps the check parser-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.assessment.posture import PostureCheckResult

if TYPE_CHECKING:
    from pathlib import Path

_SECURITY_MD_PATHS = ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md")
_DEPENDABOT_PATHS = (".github/dependabot.yml", ".github/dependabot.yaml")

# Lockfiles we recognise — kept in sync with what Trivy supports as a vuln
# source. Order matters only for ``detail.lockfiles`` deterministic output.
_LOCKFILE_GLOBS: tuple[str, ...] = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.sum",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
)


def check_security_md(repo_path: Path) -> PostureCheckResult:
    for candidate in _SECURITY_MD_PATHS:
        if (repo_path / candidate).is_file():
            return PostureCheckResult(
                check_name="security_md",
                status="pass",
                detail={"path": candidate},
            )
    return PostureCheckResult(
        check_name="security_md",
        status="fail",
        detail={"searched": list(_SECURITY_MD_PATHS)},
    )


def check_lockfile_present(repo_path: Path) -> PostureCheckResult:
    """Pass if any recognised lockfile exists anywhere in the tree."""
    hits: list[str] = []
    for glob in _LOCKFILE_GLOBS:
        for match in repo_path.rglob(glob):
            if match.is_file():
                hits.append(str(match.relative_to(repo_path)))
    if hits:
        return PostureCheckResult(
            check_name="lockfile_present",
            status="pass",
            detail={"lockfiles": hits},
        )
    return PostureCheckResult(
        check_name="lockfile_present",
        status="fail",
        detail={"searched": list(_LOCKFILE_GLOBS)},
    )


def check_dependabot_config(repo_path: Path) -> PostureCheckResult:
    for candidate in _DEPENDABOT_PATHS:
        if (repo_path / candidate).is_file():
            return PostureCheckResult(
                check_name="dependabot_config",
                status="pass",
                detail={"path": candidate},
            )
    return PostureCheckResult(
        check_name="dependabot_config",
        status="fail",
        detail={"searched": list(_DEPENDABOT_PATHS)},
    )
