"""Architect-mandated regression tests for the v0.2 dashboard payload.

Each test name is called out by name in the IMPL plan as a guard against the
specific drift points the architect flagged. These are the hard contract:

* No legacy ``scanner_versions`` / ``tool_states`` fields anywhere.
* Posture rows on the wire use four-state vocabulary
  (``pass | fail | done | advisory``); never a bare ``passed: bool``.
* The ``done`` state is a read-time projection from a posture check's
  ``pr_url`` field — no persisted column toggles state.
* Criteria responses are labeled lists, not anonymous booleans.
* Vulnerability counts split by source (``dependency | code | secret``).
* The ``summary_seen_at`` flag is server-side, idempotent, and sourced from
  the assessment row — never from a URL param or localStorage.
* Assessment-status responses carry ``steps[]`` + ``tools[]`` and the
  ``posture`` step in ``pending`` advertises the ``hint = '15 checks'``.
"""

from __future__ import annotations

import json

import pytest

from cliff.models import (
    AssessmentCreate,
    CriteriaSnapshot,
    FindingCreate,
)


def _all_met_snapshot() -> CriteriaSnapshot:
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


async def _seed_assessment(grade: str = "B", *, with_pr_url: bool = False) -> str:
    """Seed an assessment with 15 posture findings via the unified UPSERT path."""
    from cliff.assessment.posture import ADVISORY_CHECKS, CHECK_CATEGORY
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment, set_assessment_result
    from cliff.db.repo_finding import create_finding

    assert _db is not None
    repo_url = "https://github.com/a/b"
    a = await create_assessment(_db, AssessmentCreate(repo_url=repo_url))
    snap = _all_met_snapshot()
    await set_assessment_result(_db, a.id, grade=grade, criteria_snapshot=snap)

    # 15 posture checks: 11-12 pass, 1 fail (or 1 done if with_pr_url), 3 advisory.
    seeds: list[tuple[str, str, str | None]] = [
        ("branch_protection", "pass", None),
        ("no_force_pushes", "pass", None),
        ("no_secrets_in_code", "pass", None),
        ("security_md", "pass", None),
        ("lockfile_present", "pass", None),
        ("dependabot_config", "pass", None),
        ("signed_commits", "advisory", None),
        ("code_owners_exists", "fail", None),
        ("secret_scanning_enabled", "pass", None),
        (
            "actions_pinned_to_sha",
            "pass" if with_pr_url else "fail",
            "https://github.com/a/b/pull/14" if with_pr_url else None,
        ),
        ("trusted_action_sources", "pass", None),
        ("workflow_trigger_scope", "advisory", None),
        ("stale_collaborators", "pass", None),
        ("broad_team_permissions", "advisory", None),
        ("default_branch_permissions", "pass", None),
    ]
    for name, scanner_status, pr_url in seeds:
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
            _db,
            FindingCreate(
                source_type="cliff-posture",
                source_id=f"{repo_url}:{name}",
                type="posture",
                grade_impact=grade_impact,
                category=CHECK_CATEGORY.get(name, "repo_configuration"),  # type: ignore[arg-type]
                assessment_id=a.id,
                status=status,
                title=name,
                pr_url=pr_url,
                raw_payload={
                    "check_name": name,
                    "scanner_status": scanner_status,
                },
            ),
        )
    return a.id


# --------------------------------------------------------------------- guards
@pytest.mark.asyncio
async def test_dashboard_omits_legacy_scanner_versions(db_client) -> None:
    """ADR-0032 guard: the parallel scanner_versions / tool_states[] payloads
    do not appear in the dashboard response. ``tools[]`` is the single source.
    """
    await _seed_assessment(grade="B")
    resp = await db_client.get("/api/dashboard")
    body = resp.json()
    serialized = json.dumps(body)
    assert "scanner_versions" not in body
    assert "tool_states" not in body
    assert "scanner_versions" not in serialized
    assert "tool_states" not in serialized
    # The replacement payload is present.
    assert isinstance(body["tools"], list) and len(body["tools"]) >= 1


@pytest.mark.asyncio
async def test_dashboard_tools_with_results(db_client) -> None:
    """Each tools[] entry carries result.kind/value/text in the done state."""
    await _seed_assessment(grade="B")
    resp = await db_client.get("/api/dashboard")
    tools = resp.json()["tools"]
    assert len(tools) == 3
    by_id = {t["id"]: t for t in tools}
    assert {"trivy", "semgrep", "posture"} <= set(by_id)
    for tool in tools:
        assert tool["state"] == "done"
        result = tool["result"]
        assert result is not None
        assert result["kind"] in {"findings_count", "pass_count"}
        assert isinstance(result["value"], int)
        assert isinstance(result["text"], str) and result["text"]


@pytest.mark.asyncio
async def test_dashboard_grouped_posture_four_state(db_client) -> None:
    """Every posture row on the wire uses the four-state vocabulary."""
    await _seed_assessment()
    resp = await db_client.get("/api/dashboard")
    posture = resp.json()["posture"]
    assert posture is not None
    states_seen: set[str] = set()
    for category in posture["categories"]:
        for check in category["checks"]:
            assert "passed" not in check, "legacy bool field leaked"
            assert check["state"] in {"pass", "fail", "done", "advisory"}
            states_seen.add(check["state"])
    # The seed data covers pass + fail + advisory at minimum.
    assert {"pass", "fail", "advisory"} <= states_seen


@pytest.mark.asyncio
async def test_dashboard_advisory_count_excluded_from_progress(
    db_client,
) -> None:
    """Advisory checks are surfaced in advisory_count but never in
    categories[*].progress.{done,total}, which counts only grading rows.
    """
    await _seed_assessment()
    resp = await db_client.get("/api/dashboard")
    posture = resp.json()["posture"]
    assert posture["advisory_count"] >= 1
    for category in posture["categories"]:
        progress = category["progress"]
        non_advisory = [
            c for c in category["checks"] if c["grade_impact"] == "counts"
        ]
        assert progress["total"] == len(non_advisory)
        assert progress["done"] == sum(
            1 for c in non_advisory if c["state"] in ("pass", "done")
        )


@pytest.mark.asyncio
async def test_dashboard_criteria_with_labels(db_client) -> None:
    """``criteria`` is the labeled list — backend-owned labels per ADR-0032 §1.4."""
    await _seed_assessment()
    resp = await db_client.get("/api/dashboard")
    criteria = resp.json()["criteria"]
    assert isinstance(criteria, list)
    assert len(criteria) == 10
    # First entry is SECURITY.md per the order frozen in dashboard.py.
    first = criteria[0]
    assert first["key"] == "security_md_present"
    assert first["label"] == "SECURITY.md present"
    assert first["met"] is True
    keys = {row["key"] for row in criteria}
    assert "no_high_vulns" in keys
    assert "actions_pinned_to_sha" in keys


@pytest.mark.asyncio
async def test_dashboard_vulnerabilities_by_source_split(
    db_client,
) -> None:
    """vulnerabilities.by_source has the three buckets even when zero."""
    await _seed_assessment()
    resp = await db_client.get("/api/dashboard")
    vulns = resp.json()["vulnerabilities"]
    assert vulns is not None
    by_source = vulns["by_source"]
    assert {"dependency", "code", "secret"} <= set(by_source)
    # tool_credits is a list (possibly empty) — never a bare string.
    assert isinstance(vulns["tool_credits"], list)


@pytest.mark.asyncio
async def test_dashboard_posture_done_row_links_to_pr(
    db_client,
) -> None:
    """When a posture check has ``pr_url`` populated, the wire state is 'done'
    and the URL surfaces on the same row — the architect's read-time projection
    rule from ADR-0032 §1.2.
    """
    await _seed_assessment(with_pr_url=True)
    resp = await db_client.get("/api/dashboard")
    posture = resp.json()["posture"]
    done_rows = [
        c
        for category in posture["categories"]
        for c in category["checks"]
        if c["state"] == "done"
    ]
    assert done_rows, "expected at least one posture check projected to 'done'"
    assert any(
        c["pr_url"] and c["pr_url"].startswith("https://github.com/") for c in done_rows
    )


@pytest.mark.asyncio
async def test_mark_summary_seen_flips_timestamp(db_client) -> None:
    """First call writes summary_seen_at to now(); the second is idempotent."""
    aid = await _seed_assessment()

    # Before: summary_seen_at is null.
    pre = await db_client.get(f"/api/assessment/status/{aid}")
    assert pre.json()["summary_seen_at"] is None

    first = await db_client.post(f"/api/assessment/{aid}/mark-summary-seen")
    assert first.status_code == 200
    first_ts = first.json()["summary_seen_at"]
    assert first_ts

    second = await db_client.post(f"/api/assessment/{aid}/mark-summary-seen")
    assert second.status_code == 200
    assert second.json()["summary_seen_at"] == first_ts


@pytest.mark.asyncio
async def test_assessment_status_returns_steps_and_tools(
    db_client,
) -> None:
    aid = await _seed_assessment()
    resp = await db_client.get(f"/api/assessment/status/{aid}")
    body = resp.json()
    assert "steps" in body and isinstance(body["steps"], list) and body["steps"]
    assert "tools" in body and isinstance(body["tools"], list) and body["tools"]
    keys = {s["key"] for s in body["steps"]}
    assert {"detect", "trivy_vuln", "posture", "descriptions"} <= keys


@pytest.mark.asyncio
async def test_assessment_status_step_hint_for_posture(
    db_client,
) -> None:
    """While the posture step is pending, it carries a ``hint`` of '15 checks'
    so the UI can render the intent before the run starts.
    """
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment

    assert _db is not None
    a = await create_assessment(
        _db, AssessmentCreate(repo_url="https://github.com/a/b")
    )
    resp = await db_client.get(f"/api/assessment/status/{a.id}")
    posture_step = next(
        (s for s in resp.json()["steps"] if s["key"] == "posture"), None
    )
    assert posture_step is not None
    assert posture_step["state"] in {"pending", "running"}
    if posture_step["state"] == "pending":
        assert posture_step["hint"] == "15 checks"
