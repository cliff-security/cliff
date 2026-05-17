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
    # Issue-framed titles — when the check fails (status='new'), the title
    # describes the *problem* so the row reads as a real action item.
    # Passing-state rows carry the same title in the DB but are hidden
    # from the Issues page by the type+status filter; if they ever surface
    # the title slightly mis-frames the resolved state, which we accept
    # in exchange for the failing-row UX win.
    "branch_protection": "Branch protection not enabled on default branch",
    "no_force_pushes": "Force pushes allowed on default branch",
    "no_secrets_in_code": "Secrets committed in repository",
    "security_md": "SECURITY.md missing",
    "lockfile_present": "Lockfile missing",
    "dependabot_config": "Dependabot/Renovate not configured",
    "signed_commits": "Commits not signed",
    "code_owners_exists": "CODEOWNERS file missing",
    "secret_scanning_enabled": "Secret scanning disabled",
    "actions_pinned_to_sha": "GitHub Actions not pinned to SHA",
    "trusted_action_sources": "Untrusted GitHub Action sources",
    "workflow_trigger_scope": "Workflow trigger scope too permissive",
    "stale_collaborators": "Stale collaborators with write access",
    "broad_team_permissions": "Team permissions too broad",
    "default_branch_permissions": "Default branch permissions too broad",
}

# Severity per check. Calibrated so:
#   high   = active detection control OR direct secret/access exposure
#   medium = supply-chain hygiene, access creep, or visibility-loss gap
#   low    = process/advisory — important but not a live exposure
CHECK_SEVERITY: dict[PostureCheckName, str] = {
    "branch_protection": "high",
    "no_force_pushes": "medium",
    "no_secrets_in_code": "high",
    "security_md": "low",
    "lockfile_present": "medium",
    "dependabot_config": "medium",
    "signed_commits": "low",
    "code_owners_exists": "low",
    "secret_scanning_enabled": "high",
    "actions_pinned_to_sha": "medium",
    "trusted_action_sources": "medium",
    "workflow_trigger_scope": "low",
    "stale_collaborators": "medium",
    "broad_team_permissions": "medium",
    "default_branch_permissions": "medium",
}

# Short, agent-readable description of why each check matters and what
# "fixed" looks like. Surfaced as the finding's ``description`` so the
# remediation planner has the same context a human reviewer would.
CHECK_DESCRIPTION: dict[PostureCheckName, str] = {
    "branch_protection": (
        "The default branch has no protection rule, so anyone with push access "
        "can land code without review, CI, or status checks. Enable branch "
        "protection on the default branch and require at least one approving "
        "pull-request review plus passing status checks before merge."
    ),
    "no_force_pushes": (
        "Force pushes to the default branch are allowed, which means history can "
        "be rewritten and audited commits silently lost. Turn off force pushes in "
        "the default branch's protection rule."
    ),
    "no_secrets_in_code": (
        "A static secret scan flagged credentials in the repository tree. Rotate "
        "the secret immediately, remove it from the codebase, and move it into "
        "the secrets manager. Add a pre-commit secret-scan hook to keep new ones "
        "out."
    ),
    "security_md": (
        "The repo has no SECURITY.md, so external researchers have no documented "
        "way to report vulnerabilities. Add a SECURITY.md at the repo root with "
        "a reporting contact and disclosure policy."
    ),
    "lockfile_present": (
        "A package manifest exists without a matching lockfile, so dependency "
        "resolution drifts between machines and CI. Commit the appropriate "
        "lockfile (package-lock.json, poetry.lock, Cargo.lock, etc.) so installs "
        "are reproducible and Dependabot can pin upgrades."
    ),
    "dependabot_config": (
        "No Dependabot or Renovate configuration is present, so the project gets "
        "no automatic alerts or PRs when its dependencies have known CVEs. Add "
        ".github/dependabot.yml (or renovate.json) covering every ecosystem in "
        "the repo."
    ),
    "signed_commits": (
        "Recent commits on the default branch are not GPG/SSH-signed, so commit "
        "authorship can't be cryptographically verified. Encourage maintainers "
        "to sign commits and enable 'Require signed commits' on the default "
        "branch's protection rule."
    ),
    "code_owners_exists": (
        "There is no CODEOWNERS file, so reviewers aren't auto-assigned on "
        "sensitive paths and no one is accountable for them. Add CODEOWNERS at "
        ".github/CODEOWNERS mapping the security-critical paths to the right "
        "team handles."
    ),
    "secret_scanning_enabled": (
        "GitHub's secret-scanning feature is off for this repository, so any "
        "credential that lands on the default branch will not trigger an alert. "
        "Enable secret scanning (and push protection if available) in the repo's "
        "Security settings."
    ),
    "actions_pinned_to_sha": (
        "GitHub Actions workflows reference third-party actions by tag (@v3) "
        "instead of by commit SHA, so a compromised tag silently pulls malicious "
        "code into CI. Pin every third-party action to a full 40-char commit "
        "SHA."
    ),
    "trusted_action_sources": (
        "CI workflows pull actions from publishers outside an allowlist of "
        "trusted vendors. Restrict the Actions allowlist (Settings → Actions → "
        "General) to GitHub-verified creators and your approved third parties."
    ),
    "workflow_trigger_scope": (
        "One or more workflows use a permissive trigger (e.g. pull_request_target "
        "or write-mode token on a fork PR) that an attacker can abuse from an "
        "untrusted fork. Audit each workflow's triggers and token permissions; "
        "default to GITHUB_TOKEN: read-only."
    ),
    "stale_collaborators": (
        "Collaborators with write access haven't shown activity in the last 90 "
        "days. Stale access is access an attacker can take over. Remove "
        "inactive collaborators or downgrade them to read."
    ),
    "broad_team_permissions": (
        "A team has admin or maintain on the repo when write or triage would "
        "suffice. Tighten the team's permission to the least it needs for its "
        "actual workflow."
    ),
    "default_branch_permissions": (
        "Too many roles can push directly to the default branch. Restrict push "
        "to a small set of maintainers and enforce PRs for everyone else via "
        "branch protection."
    ),
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
    # Q01R-B23 — ``branch`` no longer defaults to ``main``. Defaulting hid
    # the bug where every master-default repo (NodeGoat and friends) got
    # 403 on ``/branches/main/protection`` and 404 on
    # ``/commits?sha=main``. Callers must resolve the real default branch
    # (typically via ``GithubClient.get_repo_info`` -> ``default_branch``)
    # and pass it through explicitly.
    branch: str


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
    "CHECK_DESCRIPTION",
    "CHECK_DISPLAY_NAME",
    "CHECK_SEVERITY",
    "GithubAPI",
    "PostureCheckResult",
    "RepoCoords",
    "run_all_posture_checks",
]
