"""Unit tests for ``WorkspaceDirManager.create_repo_workspace`` (IMPL-0002 E4)."""

from __future__ import annotations

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
        assert (ws_dir / "history").is_dir()
        assert (ws_dir / "history" / "agent-runs.jsonl").is_file()

        # No finding-scoped files on a repo workspace.
        assert not (ws_dir / "finding.json").exists()
        assert not (ws_dir / "finding.md").exists()
        assert not (ws_dir / "CONTEXT.md").exists()

        # No OpenCode scaffolding — the PA repo-action agent carries its own
        # prompt + permission policy (ADR-0047); nothing is rendered to disk.
        assert not (ws_dir / ".opencode").exists()
        assert not (ws_dir / "opencode.json").exists()

        # REPO_ACTION.md summary exists and mentions the action + URL.
        action_md = (ws_dir / "REPO_ACTION.md").read_text()
        assert "repo_action_security_md" in action_md
        assert "https://github.com/acme/widget" in action_md


class TestDependabotRepoWorkspace:
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
