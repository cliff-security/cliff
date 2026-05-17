"""UPSERT preservation tests for the unified ``finding`` table (ADR-0027).

Implements the IMPL-0003-p2 §"UPSERT preservation table" contract: re-running
``create_finding`` for the same ``(source_type, source_id)`` preserves user
lifecycle / agent-set fields and refreshes scanner truth. The type-conditional
rule is tested separately: ``status`` is REFRESHED for ``type='posture'`` and
PRESERVED for everything else.
"""

from __future__ import annotations

from cliff.db.repo_finding import create_finding, get_finding, list_findings
from cliff.models import FindingCreate


async def test_upsert_preserves_id_and_created_at_on_conflict(db) -> None:
    seed = FindingCreate(
        source_type="trivy",
        source_id="lodash@4.17.19:CVE-2021-23337",
        type="dependency",
        title="t",
    )
    first = await create_finding(db, seed)
    again = await create_finding(db, seed)
    assert first.id == again.id
    assert first.created_at == again.created_at


async def test_upsert_preserves_status_when_user_triaged(db) -> None:
    seed = FindingCreate(
        source_type="trivy",
        source_id="ssrf:1",
        type="dependency",
        title="ssrf",
    )
    first = await create_finding(db, seed)
    # Simulate a user marking the finding as triaged.
    from cliff.db.repo_finding import update_finding
    from cliff.models import FindingUpdate

    await update_finding(db, first.id, FindingUpdate(status="triaged"))

    refreshed = await create_finding(db, seed)
    assert refreshed.status == "triaged"


async def test_upsert_preserves_likely_owner_plain_description_why_this_matters(db) -> None:
    seed = FindingCreate(
        source_type="trivy",
        source_id="rce:1",
        type="dependency",
        title="rce",
    )
    first = await create_finding(db, seed)
    from cliff.db.repo_finding import update_finding
    from cliff.models import FindingUpdate

    await update_finding(
        db,
        first.id,
        FindingUpdate(
            likely_owner="@alice",
            plain_description="LLM-generated one-liner.",
            why_this_matters="Agent's evidence note.",
        ),
    )
    refreshed = await create_finding(db, seed)
    assert refreshed.likely_owner == "@alice"
    assert refreshed.plain_description == "LLM-generated one-liner."
    assert refreshed.why_this_matters == "Agent's evidence note."


async def test_upsert_preserves_pr_url_set_by_agent(db) -> None:
    seed = FindingCreate(
        source_type="cliff-posture",
        source_id="https://github.com/a/b:security_md",
        type="posture",
        title="security_md",
    )
    first = await create_finding(db, seed)
    from cliff.db.repo_finding import update_finding
    from cliff.models import FindingUpdate

    await update_finding(
        db,
        first.id,
        FindingUpdate(pr_url="https://github.com/a/b/pull/14"),
    )
    refreshed = await create_finding(db, seed)
    assert refreshed.pr_url == "https://github.com/a/b/pull/14"


async def test_upsert_refreshes_title_description_raw_severity_normalized_priority(db) -> None:
    seed = FindingCreate(
        source_type="trivy",
        source_id="x:1",
        type="dependency",
        title="old title",
        description="old desc",
        raw_severity="LOW",
        normalized_priority="low",
    )
    await create_finding(db, seed)
    refreshed = await create_finding(
        db,
        seed.model_copy(
            update={
                "title": "new title",
                "description": "new desc",
                "raw_severity": "HIGH",
                "normalized_priority": "high",
            }
        ),
    )
    assert refreshed.title == "new title"
    assert refreshed.description == "new desc"
    assert refreshed.raw_severity == "HIGH"
    assert refreshed.normalized_priority == "high"


async def test_upsert_refreshes_raw_payload_type_grade_impact_category(db) -> None:
    seed = FindingCreate(
        source_type="cliff-posture",
        source_id="https://github.com/a/b:lockfile_present",
        type="posture",
        grade_impact="counts",
        category="repo_configuration",
        title="lockfile_present",
        raw_payload={"v": 1},
    )
    await create_finding(db, seed)
    refreshed = await create_finding(
        db,
        seed.model_copy(
            update={
                "grade_impact": "advisory",
                "category": "ci_supply_chain",
                "raw_payload": {"v": 2},
            }
        ),
    )
    assert refreshed.grade_impact == "advisory"
    assert refreshed.category == "ci_supply_chain"
    assert refreshed.raw_payload == {"v": 2}


async def test_upsert_refreshes_assessment_id_and_updated_at(db) -> None:
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    a1 = await create_assessment(db, AssessmentCreate(repo_url="https://x/a"))
    a2 = await create_assessment(db, AssessmentCreate(repo_url="https://x/a"))

    seed = FindingCreate(
        source_type="trivy",
        source_id="upd:1",
        type="dependency",
        assessment_id=a1.id,
        title="t",
    )
    first = await create_finding(db, seed)
    refreshed = await create_finding(
        db, seed.model_copy(update={"assessment_id": a2.id})
    )
    assert refreshed.assessment_id == a2.id
    assert refreshed.updated_at >= first.updated_at


# --------------------------------------------------------------------- type-conditional


async def test_upsert_refreshes_status_for_posture_only(db) -> None:
    """Posture: status REFRESHES (scanner is truth). Non-posture: PRESERVES."""
    posture_seed = FindingCreate(
        source_type="cliff-posture",
        source_id="https://github.com/a/b:branch_protection",
        type="posture",
        title="branch_protection",
        status="new",
    )
    await create_finding(db, posture_seed)
    refreshed_posture = await create_finding(
        db, posture_seed.model_copy(update={"status": "passed"})
    )
    assert refreshed_posture.status == "passed"

    dep_seed = FindingCreate(
        source_type="trivy",
        source_id="x:1",
        type="dependency",
        title="x",
        status="new",
    )
    first = await create_finding(db, dep_seed)
    from cliff.db.repo_finding import update_finding
    from cliff.models import FindingUpdate

    await update_finding(db, first.id, FindingUpdate(status="in_progress"))
    refreshed_dep = await create_finding(
        db, dep_seed.model_copy(update={"status": "new"})
    )
    assert refreshed_dep.status == "in_progress"  # preserved


async def test_list_findings_filters_by_type_and_assessment_id(db) -> None:
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    a = await create_assessment(db, AssessmentCreate(repo_url="https://x/a"))
    await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="dep:1",
            type="dependency",
            assessment_id=a.id,
            title="d1",
        ),
    )
    await create_finding(
        db,
        FindingCreate(
            source_type="cliff-posture",
            source_id="https://github.com/a/b:security_md",
            type="posture",
            assessment_id=a.id,
            title="security_md",
        ),
    )
    deps = await list_findings(db, type="dependency", assessment_id=a.id)
    posture = await list_findings(db, type="posture", assessment_id=a.id)
    assert len(deps) == 1
    assert len(posture) == 1


async def test_get_finding_round_trip_with_v0_2_columns(db) -> None:
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    a = await create_assessment(db, AssessmentCreate(repo_url="https://x/a"))
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="x:1",
            type="dependency",
            grade_impact="counts",
            category=None,
            assessment_id=a.id,
            title="x",
            pr_url="https://github.com/a/b/pull/9",
        ),
    )
    fetched = await get_finding(db, finding.id)
    assert fetched is not None
    assert fetched.type == "dependency"
    assert fetched.grade_impact == "counts"
    assert fetched.assessment_id == a.id
    assert fetched.pr_url == "https://github.com/a/b/pull/9"
