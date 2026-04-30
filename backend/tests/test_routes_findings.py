"""Tests for Finding CRUD endpoints."""

from __future__ import annotations

import pytest


@pytest.fixture
def finding_payload():
    return {
        "source_type": "tenable",
        "source_id": "vuln-001",
        "title": "CVE-2024-1234 in libfoo",
        "description": "Remote code execution via buffer overflow",
        "raw_severity": "critical",
        "normalized_priority": "P1",
        "asset_id": "srv-web-01",
        "asset_label": "Web Server 01",
        "status": "new",
    }


async def test_create_finding(db_client, finding_payload):
    resp = await db_client.post("/api/findings", json=finding_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == finding_payload["title"]
    assert data["status"] == "new"
    assert data["id"]
    assert data["created_at"]


async def test_list_findings(db_client, finding_payload):
    await db_client.post("/api/findings", json=finding_payload)
    await db_client.post("/api/findings", json={**finding_payload, "source_id": "vuln-002"})

    resp = await db_client.get("/api/findings")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_list_findings_filter_by_status(db_client, finding_payload):
    await db_client.post("/api/findings", json=finding_payload)
    await db_client.post(
        "/api/findings", json={**finding_payload, "source_id": "vuln-002", "status": "triaged"}
    )

    resp = await db_client.get("/api/findings", params={"status": "triaged"})
    assert resp.status_code == 200
    findings = resp.json()
    assert len(findings) == 1
    assert findings[0]["status"] == "triaged"


async def test_get_finding(db_client, finding_payload):
    create_resp = await db_client.post("/api/findings", json=finding_payload)
    finding_id = create_resp.json()["id"]

    resp = await db_client.get(f"/api/findings/{finding_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == finding_id


async def test_get_finding_not_found(db_client):
    resp = await db_client.get("/api/findings/nonexistent")
    assert resp.status_code == 404


async def test_update_finding(db_client, finding_payload):
    create_resp = await db_client.post("/api/findings", json=finding_payload)
    finding_id = create_resp.json()["id"]

    resp = await db_client.patch(
        f"/api/findings/{finding_id}", json={"status": "triaged", "likely_owner": "platform-team"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "triaged"
    assert data["likely_owner"] == "platform-team"


async def test_update_finding_not_found(db_client):
    resp = await db_client.patch("/api/findings/nonexistent", json={"status": "triaged"})
    assert resp.status_code == 404


async def test_delete_finding(db_client, finding_payload):
    create_resp = await db_client.post("/api/findings", json=finding_payload)
    finding_id = create_resp.json()["id"]

    resp = await db_client.delete(f"/api/findings/{finding_id}")
    assert resp.status_code == 204

    resp = await db_client.get(f"/api/findings/{finding_id}")
    assert resp.status_code == 404


async def test_delete_finding_not_found(db_client):
    resp = await db_client.delete("/api/findings/nonexistent")
    assert resp.status_code == 404


async def test_list_findings_includes_derived(db_client, finding_payload):
    """IMPL-0006 T2 — every finding in the list response carries a derived block.

    Phase-1 scope: ``derived`` is populated for every finding (todo when no
    workspace exists). The shape is ``{section, stage, workspace_id, pr_url}``.
    """
    await db_client.post("/api/findings", json=finding_payload)

    resp = await db_client.get("/api/findings")
    assert resp.status_code == 200
    findings = resp.json()
    assert len(findings) == 1
    assert "derived" in findings[0]
    derived = findings[0]["derived"]
    assert derived["section"] == "todo"
    assert derived["stage"] == "todo"
    assert derived["workspace_id"] is None
    assert derived["pr_url"] is None


async def test_get_finding_includes_derived(db_client, finding_payload):
    create_resp = await db_client.post("/api/findings", json=finding_payload)
    finding_id = create_resp.json()["id"]

    resp = await db_client.get(f"/api/findings/{finding_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["derived"]["section"] == "todo"
    assert body["derived"]["stage"] == "todo"


async def test_pagination(db_client, finding_payload):
    for i in range(5):
        await db_client.post("/api/findings", json={**finding_payload, "source_id": f"v-{i}"})

    resp = await db_client.get("/api/findings", params={"limit": 2, "offset": 0})
    assert len(resp.json()) == 2

    resp = await db_client.get("/api/findings", params={"limit": 2, "offset": 4})
    assert len(resp.json()) == 1


async def test_list_findings_scope_current_includes_posture(db_client):
    """``scope=current`` must surface posture findings alongside CVE rows.

    Previously the route filtered to ``["dependency","code","secret"]`` so
    posture rows lived only on the dashboard. Users driving /secure-repo
    couldn't see or fix failing posture checks from the Issues page or CLI.
    """
    from opensec.assessment.posture import ADVISORY_CHECKS
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment
    from opensec.db.repo_finding import create_finding
    from opensec.models import AssessmentCreate, FindingCreate

    assert _db is not None
    repo_url = "https://github.com/a/b"
    a = await create_assessment(_db, AssessmentCreate(repo_url=repo_url))

    # One CVE finding + one failing posture check, both attached to the
    # current assessment.
    await create_finding(
        _db,
        FindingCreate(
            source_type="trivy",
            source_id="cve-1",
            type="dependency",
            assessment_id=a.id,
            title="CVE-XXXX-NNNN",
            normalized_priority="P1",
        ),
    )
    name = "actions_pinned_to_sha"
    is_advisory = name in ADVISORY_CHECKS
    await create_finding(
        _db,
        FindingCreate(
            source_type="opensec-posture",
            source_id=f"{repo_url}:{name}",
            type="posture",
            grade_impact="advisory" if is_advisory else "counts",
            category="repo_configuration",
            assessment_id=a.id,
            status="new",
            title=name,
        ),
    )

    resp = await db_client.get("/api/findings", params={"scope": "current"})
    assert resp.status_code == 200
    rows = resp.json()
    types = {r["type"] for r in rows}
    assert "posture" in types, (
        f"posture must surface under scope=current; got types={types}"
    )
    assert "dependency" in types


async def test_filter_has_workspace(db_client, finding_payload):
    # Create two findings.
    r1 = await db_client.post("/api/findings", json=finding_payload)
    r2 = await db_client.post(
        "/api/findings", json={**finding_payload, "source_id": "vuln-002"}
    )
    f1_id = r1.json()["id"]

    # Create a workspace for finding 1 only.
    await db_client.post("/api/workspaces", json={"finding_id": f1_id})

    # has_workspace=true → only finding 1
    resp = await db_client.get("/api/findings", params={"has_workspace": "true"})
    ids = {f["id"] for f in resp.json()}
    assert f1_id in ids
    assert r2.json()["id"] not in ids

    # has_workspace=false → only finding 2
    resp = await db_client.get("/api/findings", params={"has_workspace": "false"})
    ids = {f["id"] for f in resp.json()}
    assert r2.json()["id"] in ids
    assert f1_id not in ids
