"""Route tests for D5 completion share-action (IMPL-0002)."""

from __future__ import annotations

import pytest

from cliff.models import AssessmentCreate, CompletionCreate, CriteriaSnapshot


@pytest.fixture
def criteria():
    return CriteriaSnapshot(
        no_critical_vulns=True,
        posture_checks_passing=5,
        posture_checks_total=5,
        security_md_present=True,
        dependabot_present=True,
    )


async def _seed_completion(criteria: CriteriaSnapshot) -> str:
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment
    from cliff.db.dao.completion import create_completion

    assert _db is not None
    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    c = await create_completion(
        _db,
        CompletionCreate(
            assessment_id=a.id,
            repo_url="https://github.com/a/b",
            criteria_snapshot=criteria,
        ),
    )
    return c.id


async def test_record_share_action_happy_path(db_client, criteria):
    cid = await _seed_completion(criteria)

    resp = await db_client.post(
        f"/api/completion/{cid}/share-action", json={"action": "download"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completion_id"] == cid
    assert data["share_actions_used"] == ["download"]


async def test_record_share_action_is_idempotent(db_client, criteria):
    cid = await _seed_completion(criteria)

    await db_client.post(f"/api/completion/{cid}/share-action", json={"action": "download"})
    resp = await db_client.post(
        f"/api/completion/{cid}/share-action", json={"action": "download"}
    )
    assert resp.status_code == 200
    assert resp.json()["share_actions_used"] == ["download"]


async def test_record_share_action_orders_distinct_actions(db_client, criteria):
    cid = await _seed_completion(criteria)

    await db_client.post(f"/api/completion/{cid}/share-action", json={"action": "download"})
    await db_client.post(f"/api/completion/{cid}/share-action", json={"action": "copy_text"})
    resp = await db_client.post(
        f"/api/completion/{cid}/share-action", json={"action": "copy_markdown"}
    )
    assert resp.status_code == 200
    assert resp.json()["share_actions_used"] == ["download", "copy_text", "copy_markdown"]


async def test_record_share_action_unknown_completion_returns_404(db_client):
    resp = await db_client.post(
        "/api/completion/nope/share-action", json={"action": "download"}
    )
    assert resp.status_code == 404


async def test_record_share_action_invalid_action_returns_422(db_client, criteria):
    cid = await _seed_completion(criteria)
    resp = await db_client.post(
        f"/api/completion/{cid}/share-action", json={"action": "teleport"}
    )
    assert resp.status_code == 422
