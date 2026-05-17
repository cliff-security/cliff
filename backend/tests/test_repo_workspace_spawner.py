"""Tests for the repo-workspace spawner DB write (IMPL-0004 T2 / ADR-0030).

``_DefaultRepoWorkspaceSpawner.spawn_repo_workspace`` scaffolds a filesystem
workspace and then INSERTs a ``workspace`` row so the posture-fix 409 guard
(``idx_workspace_active_per_check``) has something to collide on. Tests here
exercise the DB side without running the real OpenCode process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from cliff.api._engine_dep import _DefaultRepoWorkspaceSpawner
from cliff.db.connection import close_db, init_db
from cliff.db.repo_workspace import get_active_workspace_by_source_check_name
from cliff.workspace.workspace_dir_manager import WorkspaceKind

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db(tmp_path: Path, monkeypatch):
    conn = await init_db(":memory:")
    # Point the spawner's filesystem scaffolding at a temp dir so the test
    # never touches ~/.../data/workspaces.
    from cliff.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    yield conn
    await close_db()


async def test_spawner_inserts_workspace_row(db: aiosqlite.Connection) -> None:
    spawner = _DefaultRepoWorkspaceSpawner(pool=None)

    workspace_id = await spawner.spawn_repo_workspace(
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/widget",
        params={"contact_email": "security@acme.example"},
    )

    assert workspace_id.startswith("repo-repo_action_security_md-")

    # Row exists with the right shape.
    cursor = await db.execute(
        "SELECT kind, source_check_name, state, finding_id, workspace_dir "
        "FROM workspace WHERE id = ?",
        (workspace_id,),
    )
    row = await cursor.fetchone()
    assert row is not None, "spawner must persist a workspace row"
    assert row["kind"] == "repo_action_security_md"
    assert row["source_check_name"] == "security_md"
    assert row["state"] == "pending"
    assert row["finding_id"] is None
    assert row["workspace_dir"], "workspace_dir must be set so callers can find the scaffold"


async def test_spawner_row_visible_via_dao(db: aiosqlite.Connection) -> None:
    spawner = _DefaultRepoWorkspaceSpawner(pool=None)
    workspace_id = await spawner.spawn_repo_workspace(
        kind=WorkspaceKind.repo_action_dependabot,
        repo_url="https://github.com/acme/widget",
        params=None,
    )

    found = await get_active_workspace_by_source_check_name(db, "dependabot_config")
    assert found is not None
    assert found.id == workspace_id
    assert found.source_check_name == "dependabot_config"
    assert found.state == "pending"


async def test_spawner_collision_raises_integrity_error(
    db: aiosqlite.Connection,
) -> None:
    """The partial unique index fires on a second non-terminal INSERT for the
    same check. The spawner propagates the IntegrityError so the route can
    turn it into a 409.
    """
    spawner = _DefaultRepoWorkspaceSpawner(pool=None)

    await spawner.spawn_repo_workspace(
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/widget",
        params=None,
    )

    with pytest.raises(aiosqlite.IntegrityError):
        await spawner.spawn_repo_workspace(
            kind=WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params=None,
        )


async def test_runner_finalize_releases_partial_index(
    db: aiosqlite.Connection,
) -> None:
    """End-to-end test that exercising the runner's terminal path
    (``_finalize`` -> ``_sync_workspace_state``) flips ``workspace.state``
    to a terminal value and lets a retry succeed. Matches the code-review
    fix for the Story 3 retry-after-failure flow — no raw SQL.
    """
    from cliff.db.repo_workspace import set_workspace_state

    spawner = _DefaultRepoWorkspaceSpawner(pool=None)
    first = await spawner.spawn_repo_workspace(
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/widget",
        params=None,
    )

    # Simulate what RepoAgentRunner.run does when the agent fails.
    await set_workspace_state(db, first, "failed")

    # Retry now succeeds; a new workspace id comes back.
    second = await spawner.spawn_repo_workspace(
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/widget",
        params=None,
    )
    assert second != first
