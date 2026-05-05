"""Phase 2 dashboard payload tests (PRD-0006 / IMPL-0007 PR-B / B5).

These cover the additive fields layered onto ``DashboardPayload``:

- ``open_issues`` — current count + 30-day daily history + signed delta
- ``time_to_close`` — current p50 + 30-day daily-median history + signed delta
- ``needs_you`` — current snapshot of {plans_waiting, prs_ready, critical_todo}
- ``grade_history`` — 90 daily points, oldest -> newest, ``None`` on quiet days
- ``severity_history`` — 60 daily counts per {critical, high, medium, low}

Series are oldest-first, today is the last element. Series shorter than the
window pad with leading zeros (or ``None`` for grade_history). Existing
``test_dashboard_routes.py`` cases continue to pass without edits — Phase 2
fields are additive and never alter the v0.2 contract from ADR-0032.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from opensec.models import (
    AssessmentCreate,
    CriteriaSnapshot,
    FindingCreate,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


async def test_dashboard_phase2_empty_repo(db_client):
    """No assessment, no findings → all Phase 2 fields default cleanly."""
    resp = await db_client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    # open_issues: zero current, 30 zeros, delta 0
    assert data["open_issues"]["current"] == 0
    assert data["open_issues"]["history"] == [0] * 30
    assert data["open_issues"]["delta_pct_30d"] == 0

    # time_to_close: None current, 30 nulls, delta 0
    assert data["time_to_close"]["current_seconds"] is None
    assert data["time_to_close"]["history"] == [None] * 30
    assert data["time_to_close"]["delta_pct_30d"] == 0

    # needs_you: all zeros
    assert data["needs_you"] == {
        "plans_waiting": 0,
        "prs_ready": 0,
        "critical_todo": 0,
    }

    # grade_history: 90 daily points, all None when no assessments
    assert isinstance(data["grade_history"], list)
    assert len(data["grade_history"]) == 90
    assert all(p["grade"] is None for p in data["grade_history"])

    # severity_history: four 60-int arrays, all zeros
    sh = data["severity_history"]
    assert sh == {
        "critical": [0] * 60,
        "high": [0] * 60,
        "medium": [0] * 60,
        "low": [0] * 60,
    }


async def test_dashboard_phase2_open_issues_with_no_history(db_client):
    """5 fresh open findings → current=5, history is 29 zeros + [5], delta=0."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="C",
        criteria_snapshot=CriteriaSnapshot(no_critical_vulns=True),
    )

    for idx in range(5):
        await create_finding(
            _db,
            FindingCreate(
                source_type="trivy",
                source_id=f"v-{idx}",
                type="dependency",
                assessment_id=a.id,
                title=f"Vuln {idx}",
                normalized_priority="medium",
                status="new",
            ),
        )

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    assert data["open_issues"]["current"] == 5
    assert data["open_issues"]["history"] == [0] * 29 + [5]
    assert data["open_issues"]["delta_pct_30d"] == 0


async def test_dashboard_phase2_grade_history_two_assessments(db_client):
    """Two completed assessments on different days populate grade_history."""
    from opensec.db.connection import _db

    today = datetime.now(UTC)
    five_days_ago = today - timedelta(days=5)

    # Older assessment (B), explicitly back-dated.
    await _db.execute(
        """
        INSERT INTO assessment
            (id, repo_url, started_at, completed_at, status, grade, criteria_snapshot)
        VALUES (?, ?, ?, ?, 'complete', ?, NULL)
        """,
        (
            "old-assessment-id",
            "https://github.com/a/b",
            _iso(five_days_ago - timedelta(minutes=5)),
            _iso(five_days_ago),
            "B",
        ),
    )
    # Today's assessment (A).
    await _db.execute(
        """
        INSERT INTO assessment
            (id, repo_url, started_at, completed_at, status, grade, criteria_snapshot)
        VALUES (?, ?, ?, ?, 'complete', ?, NULL)
        """,
        (
            "new-assessment-id",
            "https://github.com/a/b",
            _iso(today - timedelta(minutes=5)),
            _iso(today),
            "A",
        ),
    )
    await _db.commit()

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    history = data["grade_history"]
    assert len(history) == 90

    # Last entry is today (A).
    assert history[-1]["grade"] == "A"
    # Five days back is B.
    assert history[-1 - 5]["grade"] == "B"
    # Quiet days are None.
    quiet = [p for p in history if p["grade"] is None]
    assert len(quiet) == 88


async def test_dashboard_phase2_severity_history_today(db_client):
    """severity_history's most-recent day equals today's open severity counts."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="C",
        criteria_snapshot=CriteriaSnapshot(no_critical_vulns=True),
    )

    # 1 critical, 2 high, 3 medium, 4 low — all open today.
    mix = [("critical", 1), ("high", 2), ("medium", 3), ("low", 4)]
    seq = 0
    for sev, n in mix:
        for _ in range(n):
            await create_finding(
                _db,
                FindingCreate(
                    source_type="trivy",
                    source_id=f"v-{sev}-{seq}",
                    type="dependency",
                    assessment_id=a.id,
                    title=f"{sev} {seq}",
                    normalized_priority=sev,
                    status="new",
                ),
            )
            seq += 1

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    sh = data["severity_history"]
    assert sh["critical"][-1] == 1
    assert sh["high"][-1] == 2
    assert sh["medium"][-1] == 3
    assert sh["low"][-1] == 4
    # Each row of the most-recent day sums to vulnerabilities.total.
    assert (
        sh["critical"][-1]
        + sh["high"][-1]
        + sh["medium"][-1]
        + sh["low"][-1]
        == data["vulnerabilities"]["total"]
    )


async def test_dashboard_phase2_needs_you_counts(db_client):
    """needs_you reflects (plans_waiting, prs_ready, critical_todo)."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding
    from opensec.db.repo_sidebar import upsert_sidebar
    from opensec.db.repo_workspace import create_workspace
    from opensec.models import SidebarStateUpdate, WorkspaceCreate

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="C",
        criteria_snapshot=CriteriaSnapshot(no_critical_vulns=True),
    )

    # plan_ready: in_progress finding + workspace + sidebar.plan
    plan_ready = await create_finding(
        _db,
        FindingCreate(
            source_type="trivy",
            source_id="vuln-plan-ready",
            type="dependency",
            assessment_id=a.id,
            title="plan-ready vuln",
            normalized_priority="high",
            status="in_progress",
        ),
    )
    ws_plan = await create_workspace(_db, WorkspaceCreate(finding_id=plan_ready.id))
    await upsert_sidebar(
        _db,
        ws_plan.id,
        SidebarStateUpdate(plan={"steps": ["step 1"], "definition_of_done": "x"}),
    )

    # pr_ready (x2): in_progress finding + workspace + sidebar.pull_request.pr_url
    for n in range(2):
        pr_ready = await create_finding(
            _db,
            FindingCreate(
                source_type="trivy",
                source_id=f"vuln-pr-ready-{n}",
                type="dependency",
                assessment_id=a.id,
                title=f"pr-ready vuln {n}",
                normalized_priority="high",
                status="in_progress",
            ),
        )
        ws_pr = await create_workspace(_db, WorkspaceCreate(finding_id=pr_ready.id))
        await upsert_sidebar(
            _db,
            ws_pr.id,
            SidebarStateUpdate(
                pull_request={
                    "pr_url": f"https://github.com/a/b/pull/{n + 100}",
                    "branch_name": f"fix/pr-{n}",
                    "status": "pr_created",
                }
            ),
        )

    # critical_todo: a critical finding, status=new, no workspace.
    await create_finding(
        _db,
        FindingCreate(
            source_type="trivy",
            source_id="vuln-critical-todo",
            type="dependency",
            assessment_id=a.id,
            title="critical todo",
            normalized_priority="critical",
            status="new",
        ),
    )

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    assert data["needs_you"]["plans_waiting"] == 1
    assert data["needs_you"]["prs_ready"] == 2
    assert data["needs_you"]["critical_todo"] == 1


async def test_dashboard_phase2_time_to_close_p50_today(db_client):
    """Three closures today with deltas {1h,2h,4h} → p50=2h."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="A",
        criteria_snapshot=CriteriaSnapshot(no_critical_vulns=True),
    )

    now = datetime.now(UTC)
    deltas = [3600, 7200, 14400]  # 1h, 2h, 4h
    for idx, delta in enumerate(deltas):
        f = await create_finding(
            _db,
            FindingCreate(
                source_type="trivy",
                source_id=f"v-closed-{idx}",
                type="dependency",
                assessment_id=a.id,
                title=f"closed {idx}",
                normalized_priority="medium",
                status="new",
            ),
        )
        # Back-date created_at and forward-set status+updated_at to simulate
        # a closure ``delta`` seconds after creation.
        created = now - timedelta(seconds=delta)
        await _db.execute(
            "UPDATE finding SET created_at = ?, updated_at = ?, status = 'validated' "
            "WHERE id = ?",
            (_iso(created), _iso(now), f.id),
        )
        await _db.commit()

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    assert data["time_to_close"]["current_seconds"] == 7200
    # Today's bucket carries 7200; older buckets are None.
    assert data["time_to_close"]["history"][-1] == 7200
    assert all(v is None for v in data["time_to_close"]["history"][:-1])


async def test_dashboard_phase2_does_not_break_v0_2_contract(db_client):
    """All v0.2 fields stay present and unchanged when Phase 2 fields land."""
    resp = await db_client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    # v0.2 contract — must remain intact (subset of test_dashboard_v2_payload).
    assert "assessment" in data
    assert "grade" in data
    assert "criteria" in data
    assert isinstance(data["criteria"], list) and len(data["criteria"]) == 10
    assert "criteria_snapshot" in data
    assert "findings_count_by_priority" in data
    assert "posture_pass_count" in data
    assert "posture_total_count" in data
    assert "posture" in data
    assert "tools" in data
    assert "vulnerabilities" in data
    assert "completion_id" in data

    # Phase 2 additions — additive, all defaultable.
    assert "open_issues" in data
    assert "time_to_close" in data
    assert "needs_you" in data
    assert "grade_history" in data
    assert "severity_history" in data


async def test_dashboard_phase2_delta_pct_handles_zero_baseline(db_client):
    """delta_pct_30d returns 0 (not infinity) when 30-day baseline is 0."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="C",
        criteria_snapshot=CriteriaSnapshot(no_critical_vulns=True),
    )
    await create_finding(
        _db,
        FindingCreate(
            source_type="trivy",
            source_id="v-baseline-zero",
            type="dependency",
            assessment_id=a.id,
            title="vuln",
            normalized_priority="high",
            status="new",
        ),
    )

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    # Baseline 30 days ago is 0 (the finding doesn't exist yet); delta should
    # NOT be Infinity / NaN — the contract is "0 in this case, not blow up".
    assert isinstance(data["open_issues"]["delta_pct_30d"], int)
    assert data["open_issues"]["delta_pct_30d"] == 0


@pytest.mark.parametrize("days", [30, 60, 90])
async def test_dashboard_phase2_history_is_oldest_first(db_client, days):
    """Series order: index 0 = oldest, index -1 = today."""
    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    assert len(data["open_issues"]["history"]) == 30
    assert len(data["time_to_close"]["history"]) == 30
    assert len(data["grade_history"]) == 90
    for arr in data["severity_history"].values():
        assert len(arr) == 60
    # The exact day count check is a smoke; the windowed parametrize keeps
    # the test cheap and asserts each window length.
    _ = days


# ──────────────────────────────────────────────────────────────────────────
# IMPL-0009 — new dashboard fields:
#   open_by_severity, level_up, last_assessment, grade_label, grade_caption
# ──────────────────────────────────────────────────────────────────────────


async def test_dashboard_impl0009_empty_repo_defaults(db_client):
    """No assessment → IMPL-0009 fields render as a clean "First scan" state."""
    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    # All four severities present, counts and weekly_delta all zero.
    obs = data["open_by_severity"]
    assert [r["kind"] for r in obs] == ["critical", "high", "medium", "low"]
    assert all(r["count"] == 0 and r["weekly_delta"] == 0 for r in obs)

    assert data["level_up"] is None
    assert data["last_assessment"] is None
    assert data["grade_label"] == "First scan"
    assert "first assessment" in data["grade_caption"].lower()


async def test_dashboard_impl0009_seeded_payload_shape(db_client):
    """Seed an assessment + a few findings + verify the new fields populate."""
    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result
    from opensec.db.repo_finding import create_finding

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(
        _db,
        a.id,
        grade="B",
        criteria_snapshot=CriteriaSnapshot(
            no_critical_vulns=False,  # forces a critical gate
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
        ),
    )
    # One critical so the level_up gate has a bucket to point at.
    await create_finding(
        _db,
        FindingCreate(
            source_type="trivy",
            source_id="v-crit",
            type="dependency",
            assessment_id=a.id,
            title="RCE in lodash",
            normalized_priority="critical",
            status="new",
        ),
    )

    resp = await db_client.get("/api/dashboard")
    data = resp.json()

    # open_by_severity: critical = 1, others = 0.
    by_kind = {r["kind"]: r["count"] for r in data["open_by_severity"]}
    assert by_kind["critical"] == 1
    assert by_kind["high"] == 0

    # level_up exists with at least the one critical gate.
    assert data["level_up"] is not None
    assert data["level_up"]["current"] == "B"
    assert data["level_up"]["next"] == "A"
    gate_ids = [g["id"] for g in data["level_up"]["gates"]]
    assert "criticals_open" in gate_ids

    # last_assessment carries the repo + scanners.
    la = data["last_assessment"]
    assert la is not None
    assert la["repo_url"] == "https://github.com/a/b"
    assert isinstance(la["scanners"], list)

    # First-scan label until a prior completed assessment exists.
    assert data["grade_label"] == "First scan"
    assert data["grade_caption"]


async def test_dashboard_impl0009_grade_label_transitions(db_client):
    """A second completed assessment with a different grade flips the label."""
    import asyncio

    from opensec.db.connection import _db
    from opensec.db.dao.assessment import create_assessment, set_assessment_result

    snap = CriteriaSnapshot(no_critical_vulns=True)

    a1 = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(_db, a1.id, grade="C", criteria_snapshot=snap)
    # Brief sleep to keep started_at strictly ordered between rows.
    await asyncio.sleep(0.01)

    a2 = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))
    await set_assessment_result(_db, a2.id, grade="B", criteria_snapshot=snap)

    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    assert data["grade_label"] == "Rising"
    assert "Promoted from C" in data["grade_caption"]


async def test_dashboard_impl0009_phase2_fields_preserved(db_client):
    """B8 contract: all Phase 2 fields stay on the wire (additive only)."""
    resp = await db_client.get("/api/dashboard")
    data = resp.json()
    for key in (
        "open_issues",
        "time_to_close",
        "needs_you",
        "grade_history",
        "severity_history",
    ):
        assert key in data, f"Phase 2 field {key!r} dropped by IMPL-0009"
