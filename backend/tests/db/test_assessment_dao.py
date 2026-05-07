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


# ─────────────────────────────────────────────────────────────────────────────
# Startup reconciliation — orphaned pending/running rows from killed workers.
# ─────────────────────────────────────────────────────────────────────────────


async def test_reconcile_orphaned_assessments_marks_pending_and_running_failed(db):
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reconcile_orphaned_assessments,
        set_assessment_result,
        update_assessment,
    )

    pending = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/p"))
    running = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/r"))
    await update_assessment(db, running.id, AssessmentUpdate(status="running"))
    done = await create_assessment(db, AssessmentCreate(repo_url="https://github.com/a/c"))
    await set_assessment_result(
        db,
        done.id,
        grade="A",
        criteria_snapshot=CriteriaSnapshot(
            no_critical_vulns=True,
            posture_checks_passing=5,
            posture_checks_total=5,
            security_md_present=True,
            dependabot_present=True,
        ),
    )
    already_failed = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/a/f")
    )
    await update_assessment(db, already_failed.id, AssessmentUpdate(status="failed"))

    n = await reconcile_orphaned_assessments(db)
    assert n == 2

    p = await get_assessment(db, pending.id)
    r = await get_assessment(db, running.id)
    c = await get_assessment(db, done.id)
    f = await get_assessment(db, already_failed.id)

    # Pending → failed; repo_url is preserved so the dashboard's Re-run button
    # can pre-fill, and completed_at is stamped.
    assert p is not None
    assert p.status == "failed"
    assert p.repo_url == "https://github.com/a/p"
    assert p.completed_at is not None
    # Running → failed.
    assert r is not None
    assert r.status == "failed"
    # Terminal states are untouched.
    assert c is not None
    assert c.status == "complete"
    assert f is not None
    assert f.status == "failed"

    # Idempotent: a second pass is a no-op.
    assert await reconcile_orphaned_assessments(db) == 0


async def test_reconcile_orphaned_assessments_empty_db(db):
    from opensec.db.dao.assessment import reconcile_orphaned_assessments

    assert await reconcile_orphaned_assessments(db) == 0


async def test_reconcile_orphaned_stamps_interrupted_failure_detail(db):
    """Migration 015 — startup reconcile must populate the failure-detail
    block so the dashboard renders an explanation instead of a silent
    failed row.
    """
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reconcile_orphaned_assessments,
        update_assessment,
    )

    pending = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/p")
    )
    running = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/r")
    )
    await update_assessment(db, running.id, AssessmentUpdate(status="running"))

    n = await reconcile_orphaned_assessments(db)
    assert n == 2

    for orig in (pending, running):
        a = await get_assessment(db, orig.id)
        assert a is not None
        assert a.status == "failed"
        assert a.error_kind == "interrupted"
        assert a.error_message and "interrupted" in a.error_message.lower()


async def test_reconcile_does_not_overwrite_existing_failure_detail(db):
    """A row that failed cleanly pre-restart keeps its original reason —
    reconcile only stamps the COALESCE'd default when the column is NULL.
    """
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reconcile_orphaned_assessments,
        update_assessment,
    )

    a = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/c")
    )
    await update_assessment(
        db,
        a.id,
        AssessmentUpdate(
            status="running",
            error_kind="clone_failed",
            error_message="Couldn't clone the repository",
            failed_step="clone",
        ),
    )

    await reconcile_orphaned_assessments(db)

    refreshed = await get_assessment(db, a.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    # Original kind/message survive — reconcile must not stomp them.
    assert refreshed.error_kind == "clone_failed"
    assert refreshed.error_message == "Couldn't clone the repository"
    assert refreshed.failed_step == "clone"


async def test_reap_stale_assessments_marks_old_running_rows_failed(db):
    """Watchdog: any row older than the threshold gets failed/interrupted.

    Simulates the race where a row was created but the asyncio task never
    drove it to a terminal state. Uses a tiny threshold + a brief sleep so
    the test is deterministic without time-mocking.
    """
    import asyncio as _asyncio

    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reap_stale_assessments,
        update_assessment,
    )

    fresh = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/fresh")
    )
    stale = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/stale")
    )
    await update_assessment(db, stale.id, AssessmentUpdate(status="running"))
    # Wait long enough that ``stale`` falls past the cutoff but ``fresh`` is
    # also past — so we use a bigger threshold + short sleep, then run with
    # a tiny threshold to catch only ``stale`` once we sleep again.
    await _asyncio.sleep(0.05)
    # Threshold is 1ms — both rows are older than 1ms, so both get reaped.
    reaped = await reap_stale_assessments(db, older_than_seconds=0.001)
    assert reaped == 2

    for orig in (fresh, stale):
        a = await get_assessment(db, orig.id)
        assert a is not None
        assert a.status == "failed"
        assert a.error_kind == "interrupted"
        assert a.error_message and "did not finish" in a.error_message.lower()


async def test_reap_stale_assessments_skips_recent_rows(db):
    """A row started inside the window must NOT be reaped."""
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reap_stale_assessments,
    )

    a = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/recent")
    )
    # Threshold 60s; the row is brand new, so it's well inside the window.
    reaped = await reap_stale_assessments(db, older_than_seconds=60.0)
    assert reaped == 0
    refreshed = await get_assessment(db, a.id)
    assert refreshed is not None
    assert refreshed.status == "pending"


async def test_reap_stale_assessments_ignores_terminal_rows(db, criteria_full):
    """Already-complete or already-failed rows are untouched."""
    from opensec.db.dao.assessment import (
        create_assessment,
        get_assessment,
        reap_stale_assessments,
        set_assessment_result,
        update_assessment,
    )

    done = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/done")
    )
    await set_assessment_result(
        db, done.id, grade="A", criteria_snapshot=criteria_full
    )
    failed = await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/failed")
    )
    await update_assessment(
        db,
        failed.id,
        AssessmentUpdate(status="failed", error_kind="clone_failed"),
    )

    reaped = await reap_stale_assessments(db, older_than_seconds=0.0)
    assert reaped == 0

    d = await get_assessment(db, done.id)
    f = await get_assessment(db, failed.id)
    assert d is not None and d.status == "complete"
    assert f is not None and f.status == "failed"
    assert f.error_kind == "clone_failed"
