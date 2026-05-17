"""Bootstrap config route tests."""

from __future__ import annotations


async def test_bootstrap_empty_db(db_client) -> None:
    """Both signals start false on a fresh DB."""
    resp = await db_client.get("/api/config/bootstrap")
    assert resp.status_code == 200
    assert resp.json() == {
        "onboarding_completed": False,
        "has_any_assessment": False,
    }


async def test_bootstrap_reports_assessment_presence(db_client) -> None:
    """``has_any_assessment`` flips to True once at least one row exists."""
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    assert _db is not None
    await create_assessment(
        _db, AssessmentCreate(repo_url="https://github.com/acme/x")
    )

    resp = await db_client.get("/api/config/bootstrap")
    body = resp.json()
    assert body["has_any_assessment"] is True
    assert body["onboarding_completed"] is False


async def test_bootstrap_reports_onboarding_completed(db_client) -> None:
    """``onboarding_completed`` mirrors the app_setting written by the complete endpoint."""
    from cliff.db.connection import _db
    from cliff.db.repo_setting import upsert_setting

    assert _db is not None
    await upsert_setting(_db, "onboarding.completed", {"completed": True})

    resp = await db_client.get("/api/config/bootstrap")
    body = resp.json()
    assert body["onboarding_completed"] is True
