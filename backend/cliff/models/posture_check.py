"""Posture-check literal types (PRD-0003 v0.2).

PR-B (IMPL-0003-p2 Phase 2) collapses posture into the unified ``finding``
table per ADR-0027. The Pydantic ``PostureCheck`` / ``PostureCheckCreate``
classes are gone — posture results flow through ``FindingCreate`` like every
other producer. What remains in this module is the literal-type vocabulary
(``PostureCheckName``, ``PostureCheckCategory``, ``PostureCheckStatus``) used
by the orchestrator, dashboard, and tests.
"""

from __future__ import annotations

from typing import Literal

PostureCheckStatus = Literal["pass", "fail", "advisory", "unknown"]

# 15 checks total — the 7 frozen by IMPL-0002 plus 8 added in PRD-0003 v0.2.
PostureCheckName = Literal[
    # Repo configuration
    "branch_protection",
    "no_force_pushes",
    "no_secrets_in_code",
    "security_md",
    "lockfile_present",
    # Code integrity
    "dependabot_config",
    "signed_commits",
    "code_owners_exists",
    "secret_scanning_enabled",
    # CI supply chain
    "actions_pinned_to_sha",
    "trusted_action_sources",
    "workflow_trigger_scope",
    # Collaborator hygiene
    "stale_collaborators",
    "broad_team_permissions",
    "default_branch_permissions",
]

PostureCheckCategory = Literal[
    "repo_configuration",
    "code_integrity",
    "ci_supply_chain",
    "collaborator_hygiene",
]
