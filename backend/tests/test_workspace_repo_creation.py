"""Unit tests for ``WorkspaceDirManager.create_repo_workspace`` (IMPL-0002 E4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from cliff.workspace.workspace_dir_manager import WorkspaceDirManager, WorkspaceKind

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceDirManager:
    return WorkspaceDirManager(base_dir=tmp_path / "workspaces")


class TestSecurityMdRepoWorkspace:
    def test_creates_directory_with_expected_layout(
        self, manager: WorkspaceDirManager
    ) -> None:
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={"contact_email": "security@acme.example"},
        )

        assert workspace_id.startswith("repo-repo_action_security_md-"), (
            f"workspace_id should embed the kind for debuggability, got {workspace_id!r}"
        )

        ws_dir = manager.base_dir / workspace_id
        assert ws_dir.is_dir()
        assert (ws_dir / ".opencode" / "agents").is_dir()
        assert (ws_dir / "history").is_dir()
        assert (ws_dir / "opencode.json").is_file()

        # No finding-scoped files on a repo workspace.
        assert not (ws_dir / "finding.json").exists()
        assert not (ws_dir / "finding.md").exists()
        assert not (ws_dir / "CONTEXT.md").exists()

        # REPO_ACTION.md summary exists and mentions the action + URL.
        action_md = (ws_dir / "REPO_ACTION.md").read_text()
        assert "repo_action_security_md" in action_md
        assert "https://github.com/acme/widget" in action_md

    def test_writes_rendered_agent_file(self, manager: WorkspaceDirManager) -> None:
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={"contact_email": "ciso@example.org"},
            gh_token="ghp_sekret_only_in_env",
        )

        agent_file = (
            manager.base_dir
            / workspace_id
            / ".opencode"
            / "agents"
            / "security_md_generator.md"
        )
        assert agent_file.is_file()
        content = agent_file.read_text()

        # Template substitutions landed.
        assert "https://github.com/acme/widget" in content
        assert "ciso@example.org" in content
        assert "cliff/posture/security-md" in content
        assert "gh pr create --draft" in content

        # Defence in depth: the PAT must never be persisted to disk. The agent
        # reads $GH_TOKEN from the workspace env at runtime (injected by the
        # process pool), not from the rendered prompt.
        assert "ghp_sekret_only_in_env" not in content

    def test_opencode_json_has_allow_perms_for_repo_action(
        self, manager: WorkspaceDirManager
    ) -> None:
        """Repo-action workspaces run single-shot posture agents with no
        interactive approval path — see the rationale in
        ``_build_opencode_config``. Bash/edit/webfetch/external_directory
        all default to ``allow`` for this kind of workspace so the agent
        doesn't stall on a permission prompt nobody can answer.
        """
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={},
        )
        cfg = json.loads(
            (manager.base_dir / workspace_id / "opencode.json").read_text()
        )
        assert cfg["permission"]["bash"] == "allow"
        assert cfg["permission"]["edit"] == "allow"
        assert cfg["permission"]["webfetch"] == "allow"
        assert cfg["permission"]["external_directory"] == "allow"


class TestDependabotRepoWorkspace:
    def test_selects_dependabot_template(
        self, manager: WorkspaceDirManager
    ) -> None:
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/acme/widget",
            params={},
        )

        agent_file = (
            manager.base_dir
            / workspace_id
            / ".opencode"
            / "agents"
            / "dependabot_config_generator.md"
        )
        assert agent_file.is_file()
        content = agent_file.read_text()
        assert ".github/dependabot.yml" in content
        assert "cliff/posture/dependabot" in content
        assert "https://github.com/acme/widget" in content

        # The SECURITY.md template must NOT be written for a dependabot workspace.
        assert not (
            manager.base_dir
            / workspace_id
            / ".opencode"
            / "agents"
            / "security_md_generator.md"
        ).exists()

    def test_unique_workspace_ids(self, manager: WorkspaceDirManager) -> None:
        """Two back-to-back calls must get distinct workspace_ids."""
        w1 = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/acme/widget",
            params={},
        )
        w2 = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/acme/widget",
            params={},
        )
        assert w1 != w2

    def test_workspace_id_has_no_path_separators(
        self, manager: WorkspaceDirManager
    ) -> None:
        """Workspace IDs must be a single path component regardless of input.

        This protects callers that concatenate the ID into other paths; a
        malicious or malformed ``repo_url`` must not appear in the ID.
        """
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/../../../evil",
            params={},
        )
        assert "/" not in workspace_id
        assert "\\" not in workspace_id
        assert ".." not in workspace_id
        # ID must resolve back to a direct child of base_dir.
        assert (manager.base_dir / workspace_id).parent == manager.base_dir


class TestScrubRepoUrl:
    """Regression test: credentialed URLs never land in REPO_ACTION.md."""

    def test_credentialed_url_is_scrubbed(
        self, manager: WorkspaceDirManager
    ) -> None:
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://x-access-token:ghp_leaky@github.com/acme/widget",
            params={},
        )
        summary = (manager.base_dir / workspace_id / "REPO_ACTION.md").read_text()
        assert "ghp_leaky" not in summary
        assert "x-access-token" not in summary
        assert "https://github.com/acme/widget" in summary

    def test_plain_url_passes_through(self, manager: WorkspaceDirManager) -> None:
        workspace_id = manager.create_repo_workspace(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/acme/widget",
            params={},
        )
        summary = (manager.base_dir / workspace_id / "REPO_ACTION.md").read_text()
        assert "https://github.com/acme/widget" in summary
