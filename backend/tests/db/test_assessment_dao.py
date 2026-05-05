"""Unit tests for the assessment DAO (IMPL-0002 Milestone A2)."""

from __future__ import annotations

import pytest

from opensec.models import AssessmentCreate, AssessmentUpdate, CriteriaSnapshot


@pytest.fixture
def criteria_full():
    return CriteriaSnapshot(
        no_critical_vulns=True,
        posture_checks_passing=5,
        posture_checks_total=5,
        security_md_present=True,
        dependabot_present=True,
    )


async def test_create_and_get_assessment(db):
    from opensec.db.dao.assessment import create_assessment, get_assessment

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/acme/web"))
    assert created.id
    assert created.repo_url == "https://github.com/acme/web"
    assert created.status == "pending"
    assert created.started_at is not None
    assert created.completed_at is None
    assert created.grade is None
    assert created.criteria_snapshot is None

    fetched = await get_assessment(db, created.id)
    assert fetched is not None
    assert fetched.id == created.id


async def test_get_assessment_missing(db):
    from opensec.db.dao.assessment import get_assessment

    assert await get_assessment(db, "does-not-exist") is None


async def test_update_assessment_status(db):
    from opensec.db.dao.assessment import create_assessment, get_assessment, update_assessment

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/acme/web"))
    updated = await update_assessment(db, created.id, AssessmentUpdate(status="running"))
    assert updated is not None
    assert updated.status == "running"

    fetched = await get_assessment(db, created.id)
    assert fetched.status == "running"


async def test_set_assessment_result(db, criteria_full):
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        set_assessment_result,
    )

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/acme/web"))
    result = await set_assessment_result(
        db, created.id, grade="A", criteria_snapshot=criteria_full
    )
    assert result.status == "complete"
    assert result.grade == "A"
    assert result.criteria_snapshot == criteria_full
    assert result.completed_at is not None

    fetched = await get_assessment(db, created.id)
    assert fetched.grade == "A"
    assert fetched.criteria_snapshot.no_critical_vulns is True


async def test_update_assessment_missing(db):
    from opensec.db.dao.assessment import update_assessment

    assert await update_assessment(db, "nope", AssessmentUpdate(status="failed")) is None


async def test_get_latest_assessment_picks_most_recent(db):
    import asyncio

    from opensec.db.dao.assessment import create_assessment, get_latest_assessment

    a = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/one"))
    await asyncio.sleep(0.01)
    b = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/two"))

    latest = await get_latest_assessment(db)
    assert latest is not None
    assert latest.id == b.id
    assert latest.id != a.id


async def test_get_latest_assessment_empty(db):
    from opensec.db.dao.assessment import get_latest_assessment

    assert await get_latest_assessment(db) is None


async def test_criteria_snapshot_json_roundtrip(db, criteria_full):
    from opensec.db.dao.assessment import create_assessment, get_assessment, set_assessment_result

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/acme/x"))
    await set_assessment_result(db, created.id, grade="B", criteria_snapshot=criteria_full)

    fetched = await get_assessment(db, created.id)
    assert fetched.criteria_snapshot.posture_checks_passing == 5
    assert fetched.criteria_snapshot.security_md_present is True
    assert fetched.criteria_snapshot.dependabot_present is True


# ─────────────────────────────────────────────────────────────────────────────
# IMPL-0009 — assessment scope + counter columns (commit_sha / branch /
# scanned_files / scanned_deps). Round-trip through the DAO so the dashboard
# "Last assessment" panel can render real values.
# ─────────────────────────────────────────────────────────────────────────────


async def test_scope_fields_default_to_none(db):
    from opensec.db.dao.assessment import create_assessment

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/b"))
    assert created.commit_sha is None
    assert created.branch is None
    assert created.scanned_files is None
    assert created.scanned_deps is None


async def test_update_persists_scope_fields(db):
    from opensec.db.dao.assessment import create_assessment, get_assessment, update_assessment

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/b"))
    updated = await update_assessment(
        db,
        created.id,
        AssessmentUpdate(
            commit_sha="a3f81c2",
            branch="main",
            scanned_files=4128,
            scanned_deps=312,
        ),
    )
    assert updated is not None
    assert updated.commit_sha == "a3f81c2"
    assert updated.branch == "main"
    assert updated.scanned_files == 4128
    assert updated.scanned_deps == 312

    fetched = await get_assessment(db, created.id)
    assert fetched is not None
    assert fetched.commit_sha == "a3f81c2"
    assert fetched.branch == "main"
    assert fetched.scanned_files == 4128
    assert fetched.scanned_deps == 312


async def test_partial_scope_update_leaves_others_alone(db):
    from opensec.db.dao.assessment import create_assessment, update_assessment

    created = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await update_assessment(
        db, created.id, AssessmentUpdate(commit_sha="deadbee", branch="release/1")
    )
    second = await update_assessment(db, created.id, AssessmentUpdate(scanned_files=42))
    assert second is not None
    # The first update's values must survive a later partial update.
    assert second.commit_sha == "deadbee"
    assert second.branch == "release/1"
    assert second.scanned_files == 42
    assert second.scanned_deps is None
