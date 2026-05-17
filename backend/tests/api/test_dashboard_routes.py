"""Route tests for D4 dashboard (IMPL-0002 + IMPL-0003-p2 Phase 2).

Posture rows now live in the unified ``finding`` table per ADR-0027 — the
seed step UPSERTs ``type='posture'`` rows directly instead of going through
the deleted ``posture_check`` DAO.
"""

from __future__ import annotations

import pytest

from cliff.models import (
    AssessmentCreate,
    CompletionCreate,
    CriteriaSnapshot,
    FindingCreate,
)


async def test_dashboard_empty(db_client):
    resp = await db_client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment"] is None
    assert data["grade"] is None
    # v0.2: criteria is the labeled list; criteria_snapshot keeps the legacy shape.
    assert data["criteria_snapshot"] == CriteriaSnapshot().model_dump()
    assert isinstance(data["criteria"], list) and len(data["criteria"]) == 10
    assert data["findings_count_by_priority"] == {}
    assert data["posture_pass_count"] == 0
    assert data["posture_total_count"] == 0
    assert data["completion_id"] is None


@pytest.fixture
def criteria():
    return CriteriaSnapshot(
        no_critical_vulns=True,
        posture_checks_passing=3,
        posture_checks_total=4,
        security_md_present=True,
        dependabot_present=False,
    )


async def _seed_posture(db, *, assessment_id: str, repo_url: str, mix):
    """Seed posture findings via the unified UPSERT path."""
    from cliff.assessment.posture import ADVISORY_CHECKS
    from cliff.db.repo_finding import create_finding

    for name, scanner_status in mix:
        is_advisory = name in ADVISORY_CHECKS or scanner_status == "advisory"
        if is_advisory:
            grade_impact = "advisory"
            status = "new"
        elif scanner_status == "pass":
            grade_impact = "counts"
            status = "passed"
        else:
            grade_impact = "counts"
            status = "new"
        await create_finding(
            db,
            FindingCreate(
                source_type="cliff-posture",
                source_id=f"{repo_url}:{name}",
                type="posture",
                grade_impact=grade_impact,
                category="repo_configuration",
                assessment_id=assessment_id,
                status=status,
                title=name,
                raw_payload={"check_name": name, "scanner_status": scanner_status},
            ),
        )


async def test_dashboard_seeded(db_client, criteria):
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment, set_assessment_result
    from cliff.db.dao.completion import create_completion
    from cliff.db.repo_finding import create_finding

    assert _db is not None
    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(_db, a.id, grade="B", criteria_snapshot=criteria)

    # Posture: 3 pass, 1 fail, 1 advisory (advisory counts as neither pass nor fail).
    await _seed_posture(
        _db,
        assessment_id=a.id,
        repo_url="https://github.com/a/b",
        mix=[
            ("branch_protection", "pass"),
            ("no_force_pushes", "pass"),
            ("signed_commits", "pass"),  # advisory by name
            ("security_md", "fail"),
            ("dependabot_config", "advisory"),
        ],
    )

    # Findings with mixed priorities — scoped to the current assessment so
    # the dashboard counts them (non-assessment findings are excluded by the
    # current-assessment scope filter).
    for idx, pri in enumerate(["P1", "P1", "P2", "P3"]):
        await create_finding(
            _db,
            FindingCreate(
                source_type="trivy",
                source_id=f"v-{pri}-{idx}",
                type="dependency",
                assessment_id=a.id,
                title=f"x-{pri}",
                normalized_priority=pri,
            ),
        )

    await create_completion(
        _db,
        CompletionCreate(
            assessment_id=a.id,
            repo_url="https://github.com/a/b",
            criteria_snapshot=criteria,
        ),
    )

    resp = await db_client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment"]["id"] == a.id
    assert data["grade"] == "B"
    assert data["criteria_snapshot"]["posture_checks_passing"] == 3
    assert data["findings_count_by_priority"] == {"P1": 2, "P2": 1, "P3": 1}
    # 2 pass (branch_protection, no_force_pushes — signed_commits is advisory)
    # 1 fail (security_md), 2 advisory (signed_commits + dependabot_config-as-advisory)
    assert data["posture_pass_count"] == 2
    assert data["posture_total_count"] == 3  # non-advisory only
    # Grade B + not all_met → celebration is suppressed even though a
    # completion row exists, so the dashboard does not flash a stale banner.
    assert data["completion_id"] is None


async def test_dashboard_surfaces_completion_when_grade_a_and_all_met(
    db_client,
):
    """Grade A + every criterion met → completion_id flows through."""
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment, set_assessment_result
    from cliff.db.dao.completion import create_completion

    all_met = CriteriaSnapshot(
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

    assert _db is not None
    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(_db, a.id, grade="A", criteria_snapshot=all_met)
    completion = await create_completion(
        _db,
        CompletionCreate(
            assessment_id=a.id,
            repo_url="https://github.com/a/b",
            criteria_snapshot=all_met,
        ),
    )

    resp = await db_client.get("/api/dashboard")
    assert resp.status_code == 200
    assert resp.json()["completion_id"] == completion.id
