"""Dependency container passed to every Pydantic AI ``agent.run()`` call.

The shape mirrors the inputs the OpenCode-era ``_load_workspace_data``
gathered — finding row + prior context sections — plus the per-workspace
env vars (GH_TOKEN, CLIFF_REPO_URL) the executor already resolved at the
route layer. PR #2 expands the dependency surface for tool agents
(``RunContext.deps`` is how the bash/edit/gh tools read the workspace
root and credentials); PR #1 only consumes ``finding`` + ``prior_context``
inside dynamic system-prompt helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkspaceDeps:
    """Per-run context handed to Pydantic AI as ``deps``."""

    workspace_id: str
    workspace_dir: str
    finding: dict[str, Any]
    prior_context: dict[str, dict[str, Any]] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    user_note: str | None = None
    # Repo-action workspaces (ADR-0024 security.md / dependabot generators)
    # pre-approve their tools: the user already authorised the single action
    # by clicking "open a PR", and a one-shot background run has no HITL
    # surface to prompt against. When True the ``ask`` tier auto-proceeds;
    # the ``deny`` tier (catastrophic commands) still denies.
    auto_approve: bool = False
