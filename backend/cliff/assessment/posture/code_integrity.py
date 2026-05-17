"""Code-integrity posture checks (PRD-0003 v0.2).

Two new checks:

* ``code_owners_exists`` — filesystem search across the GitHub-conventional
  CODEOWNERS locations. Pure file-existence check; no git blame heuristic at
  this stage (the generator agent in Epic 3 will produce a draft from blame).
* ``secret_scanning_enabled`` — repo setting; requires a GitHub API call. We
  return ``unknown`` if the token can't see ``security_and_analysis`` (degrades
  to ``advisory`` in the dashboard layer with the reason in detail).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.assessment.posture import PostureCheckResult
from cliff.assessment.posture.github_client import UnableToVerify

if TYPE_CHECKING:
    from pathlib import Path

    from cliff.assessment.posture import GithubAPI, RepoCoords

# CODEOWNERS canonical locations — same paths the GitHub native loader checks.
_CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")


def check_code_owners_exists(repo_path: Path) -> PostureCheckResult:
    for candidate in _CODEOWNERS_PATHS:
        if (repo_path / candidate).is_file():
            return PostureCheckResult(
                check_name="code_owners_exists",
                status="pass",
                detail={"path": candidate},
            )
    return PostureCheckResult(
        check_name="code_owners_exists",
        status="fail",
        detail={"searched": list(_CODEOWNERS_PATHS)},
    )


async def check_secret_scanning_enabled(
    gh_client: GithubAPI, coords: RepoCoords
) -> PostureCheckResult:
    """Read repo settings and look for ``security_and_analysis.secret_scanning``.

    Most PATs that work for branch-protection lookups don't have the scope to
    read this; in that case we degrade to ``unknown`` with the reason carried
    so the dashboard can render an advisory chip.
    """
    info_getter = getattr(gh_client, "get_repo_info", None)
    if info_getter is None:
        return PostureCheckResult(
            check_name="secret_scanning_enabled",
            status="unknown",
            detail={"reason": "client_unsupported"},
        )
    info = await info_getter(coords.owner, coords.repo)
    if isinstance(info, UnableToVerify):
        return PostureCheckResult(
            check_name="secret_scanning_enabled",
            status="unknown",
            detail={"reason": info.reason},
        )
    if not isinstance(info, dict):
        return PostureCheckResult(
            check_name="secret_scanning_enabled",
            status="unknown",
            detail={"reason": "unexpected_body"},
        )
    sec = (info.get("security_and_analysis") or {}) if isinstance(info, dict) else {}
    secret_scanning = (sec or {}).get("secret_scanning") or {}
    state = secret_scanning.get("status")
    if state == "enabled":
        return PostureCheckResult(
            check_name="secret_scanning_enabled",
            status="pass",
            detail={"state": state},
        )
    if state in ("disabled", None):
        return PostureCheckResult(
            check_name="secret_scanning_enabled",
            status="fail",
            detail={"state": state or "absent"},
        )
    return PostureCheckResult(
        check_name="secret_scanning_enabled",
        status="unknown",
        detail={"state": state},
    )
