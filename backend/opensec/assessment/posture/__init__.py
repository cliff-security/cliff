"""Posture-checks package (PRD-0003 rev. 2).

`run_all_posture_checks` executes the fifteen repo-hygiene checks defined in
`PostureCheckName` and returns them in a stable order. Each check belongs to
exactly one of four categories (`PostureCheckCategory`); the API layer groups
them on the report card. Where a check depends on a GitHub REST endpoint the
PAT can't reach (rate-limited, missing scope, network error), the orchestrator
returns `status='unknown'` rather than raising — the dashboard projects that
to the four-state vocab as `advisory` with the reason carried in `detail`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from opensec.models.posture_check import (  # noqa: TC001 — used at runtime in dict[K, V] annotations
    PostureCheckCategory,
    PostureCheckName,
)

if TYPE_CHECKING:
    from pathlib import Path

    from opensec.models.posture_check import PostureCheckStatus


# --------------------------------------------------------------------- metadata
CHECK_CATEGORY: dict[PostureCheckName, PostureCheckCategory] = {
    "branch_protection": "repo_configuration",
    "no_force_pushes": "repo_configuration",
    "no_secrets_in_code": "repo_configuration",
    "security_md": "repo_configuration",
    "lockfile_present": "repo_configuration",
    "dependabot_config": "code_integrity",
    "signed_commits": "code_integrity",
    "code_owners_exists": "code_integrity",
    "secret_scanning_enabled": "code_integrity",
    "actions_pinned_to_sha": "ci_supply_chain",
    "trusted_action_sources": "ci_supply_chain",
    "workflow_trigger_scope": "ci_supply_chain",
    "stale_collaborators": "collaborator_hygiene",
    "broad_team_permissions": "collaborator_hygiene",
    "default_branch_permissions": "collaborator_hygiene",
}

CHECK_DISPLAY_NAME: dict[PostureCheckName, str] = {
    "branch_protection": "Branch protection enabled",
    "no_force_pushes": "Force pushes blocked",
    "no_secrets_in_code": "No committed secrets",
    "security_md": "SECURITY.md present",
    "lockfile_present": "Lockfile present",
    "dependabot_config": "Dependabot/Renovate configured",
    "signed_commits": "Signed commits",
    "code_owners_exists": "Code owners file exists",
    "secret_scanning_enabled": "Secret scanning enabled",
    "actions_pinned_to_sha": "Actions pinned to SHA",
    "trusted_action_sources": "Trusted action sources",
    "workflow_trigger_scope": "Workflow trigger scope",
    "stale_collaborators": "No stale collaborators",
    "broad_team_permissions": "Team permissions scoped",
    "default_branch_permissions": "Default branch permissions",
}

# Checks that are advisory by design — they don't count toward the grade.
ADVISORY_CHECKS: frozenset[PostureCheckName] = frozenset(
    {"signed_commits", "workflow_trigger_scope", "broad_team_permissions"}
)

# IMPL-0009 — version of the check set surfaced on the dashboard's
# "Last assessment" panel. Bump deliberately when checks are added,
# removed, or change semantics.
POSTURE_CHECKER_VERSION: str = "1.0.0"

ALL_CHECKS: tuple[PostureCheckName, ...] = (
    # repo_configuration
    "branch_protection",
    "no_force_pushes",
    "no_secrets_in_code",
    "security_md",
    "lockfile_present",
    # code_integrity
    "dependabot_config",
    "signed_commits",
    "code_owners_exists",
    "secret_scanning_enabled",
    # ci_supply_chain
    "actions_pinned_to_sha",
    "trusted_action_sources",
    "workflow_trigger_scope",
    # collaborator_hygiene
    "stale_collaborators",
    "broad_team_permissions",
    "default_branch_permissions",
)


@dataclass(frozen=True)
class RepoCoords:
    owner: str
    repo: str
    branch: str = "main"


@dataclass(frozen=True)
class PostureCheckResult:
    check_name: PostureCheckName
    status: PostureCheckStatus
    detail: dict[str, Any] | None = None

    @property
    def category(self) -> PostureCheckCategory:
        return CHECK_CATEGORY[self.check_name]

    @property
    def display_name(self) -> str:
        return CHECK_DISPLAY_NAME[self.check_name]

    @property
    def is_advisory(self) -> bool:
        return self.check_name in ADVISORY_CHECKS


class GithubAPI(Protocol):
    async def get_branch_protection(
        self, owner: str, repo: str, branch: str
    ) -> Any: ...

    async def list_recent_commits(
        self, owner: str, repo: str, branch: str, *, limit: int = 20
    ) -> Any: ...


# --------------------------------------------------------------------- orchestrator
async def run_all_posture_checks(
    repo_path: Path,
    *,
    gh_client: GithubAPI,
    coords: RepoCoords,
    assessment_id: str = "",
) -> list[PostureCheckResult]:
    from opensec.assessment.posture.branch import (
        build_branch_protection_result,
        build_no_force_pushes_result,
        build_signed_commits_result,
    )
    from opensec.assessment.posture.ci_supply_chain import (
        check_actions_pinned_to_sha,
        check_trusted_action_sources,
        check_workflow_trigger_scope,
    )
    from opensec.assessment.posture.code_integrity import (
        check_code_owners_exists,
        check_secret_scanning_enabled,
    )
    from opensec.assessment.posture.collaborator_hygiene import (
        check_broad_team_permissions,
        check_default_branch_permissions,
        check_stale_collaborators,
    )
    from opensec.assessment.posture.files import (
        check_dependabot_config,
        check_lockfile_present,
        check_security_md,
    )
    from opensec.assessment.posture.secrets import scan_for_secrets

    # Parallel fan-out: GitHub REST calls + thread-pool FS work.
    (
        protection,
        commits,
        secrets_res,
        security_res,
        lockfile_res,
        dependabot_res,
        code_owners_res,
        actions_pin_res,
        trusted_actions_res,
        trigger_scope_res,
    ) = await asyncio.gather(
        gh_client.get_branch_protection(coords.owner, coords.repo, coords.branch),
        gh_client.list_recent_commits(coords.owner, coords.repo, coords.branch),
        asyncio.to_thread(scan_for_secrets, repo_path),
        asyncio.to_thread(check_security_md, repo_path),
        asyncio.to_thread(check_lockfile_present, repo_path),
        asyncio.to_thread(check_dependabot_config, repo_path),
        asyncio.to_thread(check_code_owners_exists, repo_path),
        asyncio.to_thread(check_actions_pinned_to_sha, repo_path),
        asyncio.to_thread(check_trusted_action_sources, repo_path),
        asyncio.to_thread(check_workflow_trigger_scope, repo_path),
    )

    # GitHub-API-only checks degrade gracefully — see module docstrings.
    secret_scanning_res = await check_secret_scanning_enabled(gh_client, coords)
    stale_collab_res = await check_stale_collaborators(gh_client, coords)
    broad_team_res = await check_broad_team_permissions(gh_client, coords)
    default_branch_perms_res = await check_default_branch_permissions(gh_client, coords)

    del assessment_id  # unused — assessment_id flows through the engine, not the orchestrator
    return [
        build_branch_protection_result(protection, coords),
        build_no_force_pushes_result(protection),
        secrets_res,
        security_res,
        lockfile_res,
        dependabot_res,
        build_signed_commits_result(commits),
        code_owners_res,
        secret_scanning_res,
        actions_pin_res,
        trusted_actions_res,
        trigger_scope_res,
        stale_collab_res,
        broad_team_res,
        default_branch_perms_res,
    ]


__all__ = [
    "ADVISORY_CHECKS",
    "ALL_CHECKS",
    "CHECK_CATEGORY",
    "CHECK_DISPLAY_NAME",
    "GithubAPI",
    "PostureCheckResult",
    "RepoCoords",
    "run_all_posture_checks",
]
