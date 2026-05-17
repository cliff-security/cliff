"""Unit tests for the completion DAO (IMPL-0002 Milestone A2 + D5)."""

from __future__ import annotations

from cliff.models import AssessmentCreate, CompletionCreate, CriteriaSnapshot


async def _new_assessment(db, repo_url: str = "https://github.com/acme/web"):
    from cliff.db.dao.assessment import create_assessment

    return await create_assessment(db, AssessmentCreate(repo_url=repo_url))


def _criteria() -> CriteriaSnapshot:
    return CriteriaSnapshot(
        no_critical_vulns=True,
        posture_checks_passing=5,
        posture_checks_total=5,
        security_md_present=True,
        dependabot_present=True,
    )


async def test_create_and_get_completion(db):
    from cliff.db.dao.completion import create_completion, get_completion

    a = await _new_assessment(db)
    created = await create_completion(
        db,
        CompletionCreate(
            assessment_id=a.id,
            repo_url=a.repo_url,
            criteria_snapshot=_criteria(),
        ),
    )
    assert created.id
    assert created.assessment_id == a.id
    assert created.repo_url == a.repo_url
    assert created.completed_at is not None
    assert created.share_actions_used == []

    fetched = await get_completion(db, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.criteria_snapshot.security_md_present is True


async def test_get_completion_missing(db):
    from cliff.db.dao.completion import get_completion

    assert await get_completion(db, "nope") is None


async def test_get_completion_for_assessment(db):
    from cliff.db.dao.completion import create_completion, get_completion_for_assessment

    a = await _new_assessment(db)
    created = await create_completion(
        db,
        CompletionCreate(assessment_id=a.id, repo_url=a.repo_url, criteria_snapshot=_criteria()),
    )
    fetched = await get_completion_for_assessment(db, a.id)
    assert fetched is not None
    assert fetched.id == created.id


async def test_record_share_action_is_idempotent(db):
    from cliff.db.dao.completion import create_completion, get_completion, record_share_action

    a = await _new_assessment(db)
    c = await create_completion(
        db,
        CompletionCreate(assessment_id=a.id, repo_url=a.repo_url, criteria_snapshot=_criteria()),
    )
    updated = await record_share_action(db, c.id, "download")
    assert updated.share_actions_used == ["download"]

    updated = await record_share_action(db, c.id, "download")
    assert updated.share_actions_used == ["download"]  # dedup

    updated = await record_share_action(db, c.id, "copy_text")
    assert updated.share_actions_used == ["download", "copy_text"]

    fetched = await get_completion(db, c.id)
    assert fetched.share_actions_used == ["download", "copy_text"]


async def test_record_share_action_missing_completion_returns_none(db):
    from cliff.db.dao.completion import record_share_action

    assert await record_share_action(db, "nonexistent", "download") is None
