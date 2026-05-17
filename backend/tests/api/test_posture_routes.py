"""Route tests for D3 posture fix (IMPL-0002).

Also covers PRD-0004 / IMPL-0004 T3: the 409 guard + retry-after-terminal
behaviour. Those tests swap in a DB-writing spawner so the partial unique
index (``idx_workspace_active_per_check``) actually fires.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

import pytest

from cliff.api._engine_dep import (
    _CHECK_NAME_FOR_KIND,
    get_repo_workspace_spawner,
)
from cliff.db.repo_workspace import create_repo_action_workspace
from cliff.main import app
from cliff.workspace.workspace_dir_manager import WorkspaceKind


@dataclass
class FakeSpawner:
    """Records calls so tests can assert agent/template wiring."""

    fixed_workspace_id: str = "ws-123"
    calls: list[dict] = field(default_factory=list)

    async def spawn_repo_workspace(
        self,
        *,
        kind: WorkspaceKind,
        repo_url: str,
        params: dict | None = None,
    ) -> str:
        self.calls.append({"kind": kind, "repo_url": repo_url, "params": params})
        return self.fixed_workspace_id


class DBWritingSpawner:
    """Exercises the real DAO (and therefore the partial unique index) without
    touching the filesystem or the OpenCode process pool.

    Lets T3 tests drive the 409 collision + retry-after-terminal scenarios
    end-to-end through the posture route.
    """

    async def spawn_repo_workspace(
        self,
        *,
        kind: WorkspaceKind,
        repo_url: str,
        params: dict | None = None,
    ) -> str:
        from cliff.db.connection import _db

        assert _db is not None, "DBWritingSpawner requires an initialised db"
        workspace_id = f"repo-{kind.value}-{secrets.token_hex(4)}"
        check_name = _CHECK_NAME_FOR_KIND[kind.value]
        await create_repo_action_workspace(
            _db,
            workspace_id=workspace_id,
            kind=kind.value,
            source_check_name=check_name,
        )
        return workspace_id


@pytest.fixture
def fake_spawner():
    spawner = FakeSpawner()
    app.dependency_overrides[get_repo_workspace_spawner] = lambda: spawner
    try:
        yield spawner
    finally:
        app.dependency_overrides.pop(get_repo_workspace_spawner, None)


@pytest.fixture
def db_writing_spawner():
    spawner = DBWritingSpawner()
    app.dependency_overrides[get_repo_workspace_spawner] = lambda: spawner
    try:
        yield spawner
    finally:
        app.dependency_overrides.pop(get_repo_workspace_spawner, None)


async def _seed_onboarded_repo(repo_url: str) -> None:
    """Minimum state so a posture fix has somewhere to run — the last assessment's repo."""
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    assert _db is not None
    await create_assessment(_db, AssessmentCreate(repo_url=repo_url))


async def test_fix_security_md(db_client, fake_spawner):
    await _seed_onboarded_repo("https://github.com/a/b")

    resp = await db_client.post("/api/posture/fix/security_md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace_id"] == "ws-123"
    assert data["check_name"] == "security_md"
    assert fake_spawner.calls == [
        {
            "kind": WorkspaceKind.repo_action_security_md,
            "repo_url": "https://github.com/a/b",
            "params": None,
        }
    ]


async def test_fix_dependabot_config(db_client, fake_spawner):
    await _seed_onboarded_repo("https://github.com/a/c")

    resp = await db_client.post("/api/posture/fix/dependabot_config")
    assert resp.status_code == 200
    assert fake_spawner.calls[0]["kind"] == WorkspaceKind.repo_action_dependabot


async def test_fix_unknown_check_returns_422(db_client, fake_spawner):
    resp = await db_client.post("/api/posture/fix/branch_protection")
    assert resp.status_code == 422
    assert fake_spawner.calls == []


# Q01R B24 — lock the contract for the two check names the dashboard
# historically advertised but the backend never supported. The frontend
# fix is the registry shrink in ``_AUTO_FIXABLE_CHECKS``; these tests
# pin the 422 shape so the registry and the route enum stay in lockstep.


async def test_fix_code_owners_exists_returns_422(db_client, fake_spawner):
    resp = await db_client.post("/api/posture/fix/code_owners_exists")
    assert resp.status_code == 422
    assert fake_spawner.calls == []
    body = resp.json()
    assert isinstance(body.get("detail"), list)
    assert body["detail"], "FastAPI 422 body must include a non-empty detail list"
    first = body["detail"][0]
    assert first.get("loc")[-1] == "check_name"
    msg = first.get("msg", "")
    assert "security_md" in msg
    assert "dependabot_config" in msg


async def test_fix_actions_pinned_to_sha_returns_422(db_client, fake_spawner):
    resp = await db_client.post("/api/posture/fix/actions_pinned_to_sha")
    assert resp.status_code == 422
    assert fake_spawner.calls == []
    body = resp.json()
    assert isinstance(body.get("detail"), list)
    assert body["detail"], "FastAPI 422 body must include a non-empty detail list"
    first = body["detail"][0]
    assert first.get("loc")[-1] == "check_name"
    msg = first.get("msg", "")
    assert "security_md" in msg
    assert "dependabot_config" in msg


async def test_fix_without_any_assessment_returns_409(db_client, fake_spawner):
    # No assessment ever run — posture fix has no repo target.
    resp = await db_client.post("/api/posture/fix/security_md")
    assert resp.status_code == 409
    assert fake_spawner.calls == []


# ---------------------------------------------------------------------------
# T3 · 409 guard on concurrent posture fix (PRD-0004 / ADR-0030)
# ---------------------------------------------------------------------------


async def test_concurrent_fix_returns_409(db_client, db_writing_spawner):
    await _seed_onboarded_repo("https://github.com/a/b")

    r1 = await db_client.post("/api/posture/fix/security_md")
    assert r1.status_code == 200
    ws1 = r1.json()["workspace_id"]

    # Second POST while the first workspace is still in a non-terminal state
    # must collide on idx_workspace_active_per_check and surface as 409.
    r2 = await db_client.post("/api/posture/fix/security_md")
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["error"] == "workspace_already_running"
    assert detail["workspace_id"] == ws1
    assert detail["check_name"] == "security_md"


async def test_retry_after_terminal(db_client, db_writing_spawner):
    """After the first workspace reaches a terminal state, a new POST for
    the same check must succeed with a new workspace id (predicate no longer
    matches the prior row).
    """
    await _seed_onboarded_repo("https://github.com/a/b")

    r1 = await db_client.post("/api/posture/fix/security_md")
    assert r1.status_code == 200
    ws1 = r1.json()["workspace_id"]

    # Transition to terminal state.
    from cliff.db.connection import _db

    assert _db is not None
    await _db.execute(
        "UPDATE workspace SET state = 'failed' WHERE id = ?", (ws1,)
    )
    await _db.commit()

    r2 = await db_client.post("/api/posture/fix/security_md")
    assert r2.status_code == 200
    ws2 = r2.json()["workspace_id"]
    assert ws2 != ws1


async def test_concurrent_fix_different_checks_both_succeed(
    db_client, db_writing_spawner
):
    """Partial-index predicate keys off source_check_name — different checks
    should not collide with each other.
    """
    await _seed_onboarded_repo("https://github.com/a/b")

    r1 = await db_client.post("/api/posture/fix/security_md")
    assert r1.status_code == 200

    r2 = await db_client.post("/api/posture/fix/dependabot_config")
    assert r2.status_code == 200
    assert r2.json()["workspace_id"] != r1.json()["workspace_id"]
