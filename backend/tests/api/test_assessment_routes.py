"""Route tests for D2 assessment run/status/latest (IMPL-0002)."""

from __future__ import annotations

import asyncio

import pytest

from opensec.api._engine_dep import get_assessment_engine
from opensec.main import app
from opensec.models import CriteriaSnapshot
from tests.fakes.assessment_engine import FakeAssessmentEngine


def _all_criteria_met() -> CriteriaSnapshot:
    return CriteriaSnapshot(
        no_critical_vulns=True,
        no_high_vulns=True,
        posture_checks_passing=15,
        posture_checks_total=15,
        security_md_present=True,
        dependabot_present=True,
        branch_protection_enabled=True,
        no_secrets_detected=True,
        actions_pinned_to_sha=True,
        no_stale_collaborators=True,
        code_owners_exists=True,
        secret_scanning_enabled=True,
    )


def _partial_criteria() -> CriteriaSnapshot:
    return CriteriaSnapshot(
        no_critical_vulns=True,
        posture_checks_passing=3,
        posture_checks_total=5,
        security_md_present=True,
        dependabot_present=False,
    )


@pytest.fixture
def fake_engine():
    engine = FakeAssessmentEngine(
        grade="A",
        criteria=_all_criteria_met(),
        posture_checks=[
            {"check_name": "branch_protection", "status": "pass"},
            {"check_name": "security_md", "status": "pass"},
        ],
    )
    app.dependency_overrides[get_assessment_engine] = lambda: engine
    try:
        yield engine
    finally:
        app.dependency_overrides.pop(get_assessment_engine, None)


async def _drain_background_tasks() -> None:
    tasks: list[asyncio.Task] = list(getattr(app.state, "assessment_tasks", []))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_run_assessment_creates_row_and_runs_engine(db_client, fake_engine):
    resp = await db_client.post(
        "/api/assessment/run", json={"repo_url": "https://github.com/a/b"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment_id"]
    assert data["status"] == "pending"

    await _drain_background_tasks()
    assert fake_engine.call_count == 1


async def test_run_assessment_persists_result_and_posture(db_client, fake_engine):
    resp = await db_client.post(
        "/api/assessment/run", json={"repo_url": "https://github.com/a/b"}
    )
    aid = resp.json()["assessment_id"]
    await _drain_background_tasks()

    from opensec.db.connection import _db
    from opensec.db.dao.assessment import get_assessment
    from opensec.db.dao.completion import get_completion_for_assessment
    from opensec.db.repo_finding import list_posture_findings

    a = await get_assessment(_db, aid)
    assert a.status == "complete"
    assert a.grade == "A"
    assert a.criteria_snapshot.posture_checks_passing == 15

    posture_rows = await list_posture_findings(_db, aid)
    names = {(r.raw_payload or {}).get("check_name") for r in posture_rows}
    assert names == {"branch_protection", "security_md"}

    # All criteria met → completion row created.
    completion = await get_completion_for_assessment(_db, aid)
    assert completion is not None
    assert completion.repo_url == "https://github.com/a/b"


async def test_run_assessment_persists_findings_emitted_by_engine(db_client):
    """Gap #3 regression test — engine-emitted findings must land in the DB.

    See docs/known-issues/session-b-handoff-gaps.md. Before Session G's fix the
    background task never iterated ``result.findings``, silently dropping every
    vulnerability the engine surfaced.
    """
    engine_findings = [
        {
            "source_type": "osv",
            "source_id": "GHSA-grv7-fg5c-xmjg",
            "title": "braces@3.0.2 vulnerable to DoS via crafted patterns",
            "description": None,
            "raw_severity": "HIGH",
            "asset_label": "braces@3.0.2",
            "raw_payload": {"advisory_id": "GHSA-grv7-fg5c-xmjg"},
        },
        {
            "source_type": "osv",
            "source_id": "GHSA-example-2",
            "title": "lodash@4.17.19 prototype pollution",
            "description": None,
            "raw_severity": "MEDIUM",
            "asset_label": "lodash@4.17.19",
            "raw_payload": {"advisory_id": "GHSA-example-2"},
        },
    ]
    engine = FakeAssessmentEngine(
        grade="B",
        criteria=_partial_criteria(),
        posture_checks=[],
        findings=engine_findings,
    )
    app.dependency_overrides[get_assessment_engine] = lambda: engine
    try:
        resp = await db_client.post(
            "/api/assessment/run", json={"repo_url": "https://github.com/a/e"}
        )
        assert resp.status_code == 200
        await _drain_background_tasks()

        from opensec.db.connection import _db
        from opensec.db.repo_finding import list_findings

        persisted = await list_findings(_db)
        engine_persisted = [f for f in persisted if f.source_type == "osv"]
        assert len(engine_persisted) == 2
        source_ids = {f.source_id for f in engine_persisted}
        assert source_ids == {"GHSA-grv7-fg5c-xmjg", "GHSA-example-2"}
    finally:
        app.dependency_overrides.pop(get_assessment_engine, None)


async def test_run_assessment_no_completion_when_criteria_unmet(db_client):
    engine = FakeAssessmentEngine(grade="D", criteria=_partial_criteria(), posture_checks=[])
    app.dependency_overrides[get_assessment_engine] = lambda: engine
    try:
        resp = await db_client.post(
            "/api/assessment/run", json={"repo_url": "https://github.com/a/c"}
        )
        aid = resp.json()["assessment_id"]
        await _drain_background_tasks()

        from opensec.db.connection import _db
        from opensec.db.dao.completion import get_completion_for_assessment

        completion = await get_completion_for_assessment(_db, aid)
        assert completion is None
    finally:
        app.dependency_overrides.pop(get_assessment_engine, None)


async def test_run_assessment_engine_failure_marks_failed(db_client):
    engine = FakeAssessmentEngine(raise_on_run=RuntimeError("boom"))
    app.dependency_overrides[get_assessment_engine] = lambda: engine
    try:
        resp = await db_client.post(
            "/api/assessment/run", json={"repo_url": "https://github.com/a/d"}
        )
        aid = resp.json()["assessment_id"]
        await _drain_background_tasks()

        from opensec.db.connection import _db
        from opensec.db.dao.assessment import get_assessment

        a = await get_assessment(_db, aid)
        assert a.status == "failed"
    finally:
        app.dependency_overrides.pop(get_assessment_engine, None)


async def test_get_assessment_status(db_client, fake_engine):
    resp = await db_client.post(
        "/api/assessment/run", json={"repo_url": "https://github.com/a/b"}
    )
    aid = resp.json()["assessment_id"]
    await _drain_background_tasks()

    resp = await db_client.get(f"/api/assessment/status/{aid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment_id"] == aid
    assert data["status"] == "complete"
    assert data["progress_pct"] == 100


async def test_get_assessment_status_not_found(db_client):
    resp = await db_client.get("/api/assessment/status/nope")
    assert resp.status_code == 404


async def test_get_latest_assessment(db_client, fake_engine):
    resp = await db_client.post(
        "/api/assessment/run", json={"repo_url": "https://github.com/a/b"}
    )
    aid = resp.json()["assessment_id"]
    await _drain_background_tasks()

    resp = await db_client.get("/api/assessment/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment"]["id"] == aid
    assert data["grade"] == "A"
    assert data["criteria"]["posture_checks_passing"] == 15
    assert data["posture_total_count"] == 2
    assert data["posture_pass_count"] == 2
    assert data["findings_count_by_priority"] == {}


async def test_get_latest_assessment_empty_returns_404(db_client):
    resp = await db_client.get("/api/assessment/latest")
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# IMPL-0009 — previous_assessment on the status response.
# ──────────────────────────────────────────────────────────────────────────


async def test_status_previous_assessment_null_on_first_scan(db_client, fake_engine):
    """First-ever assessment has no prior — previous_assessment is null."""
    resp = await db_client.post(
        "/api/assessment/run", json={"repo_url": "https://github.com/a/b"}
    )
    aid = resp.json()["assessment_id"]
    await _drain_background_tasks()

    resp = await db_client.get(f"/api/assessment/status/{aid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["previous_assessment"] is None


async def test_status_previous_assessment_populated_when_prior_exists(db_client):
    """Second run sees the first as ``previous_assessment``."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import (
        create_assessment,
        set_assessment_result,
        update_assessment,
    )
    from opensec.models import AssessmentCreate, AssessmentUpdate

    snap = _all_criteria_met()

    # Plant a completed prior with a known commit + 2 open findings under it.
    prior = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(_db, prior.id, grade="C", criteria_snapshot=snap)
    await update_assessment(_db, prior.id, AssessmentUpdate(commit_sha="deadbee"))

    from opensec.db.repo_finding import create_finding
    from opensec.models import FindingCreate

    for i in range(2):
        await create_finding(
            _db,
            FindingCreate(
                source_type="trivy",
                source_id=f"v-prior-{i}",
                type="dependency",
                assessment_id=prior.id,
                title=f"old vuln {i}",
                normalized_priority="medium",
                status="new",
            ),
        )

    # Second assessment created in 'running' state — the route reads
    # previous_assessment regardless of current status.
    current = await create_assessment(
        _db, AssessmentCreate(repo_url="https://github.com/a/b")
    )

    resp = await db_client.get(f"/api/assessment/status/{current.id}")
    assert resp.status_code == 200
    data = resp.json()
    prev = data["previous_assessment"]
    assert prev is not None
    assert prev["assessment_id"] == prior.id
    assert prev["grade"] == "C"
    assert prev["commit_sha"] == "deadbee"
    assert prev["open_count"] == 2
    assert prev["report_href"] == f"/dashboard?assessment_id={prior.id}"
