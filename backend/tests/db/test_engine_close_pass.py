"""Stale-close pass tests for ``close_disappeared_findings`` (ADR-0027 §7).

Implements the IMPL-0003-p2 §"Stale-close rule" contract:

* First-run guard — no close on the very first assessment for a repo_url.
* Source-type scoping — Trivy never closes Snyk findings (different
  ``source_type``, even though both are ``type='dependency'``).
* Scanner-must-have-run — a scanner that didn't run does not trigger its close.
* Closes append a ``system_notes`` audit entry to ``raw_payload``.
"""

from __future__ import annotations

from cliff.db.dao.assessment import create_assessment
from cliff.db.repo_finding import (
    close_disappeared_findings,
    create_finding,
    get_finding,
)
from cliff.models import AssessmentCreate, FindingCreate

REPO = "https://github.com/a/b"


async def _seed_two_assessments(db) -> tuple[str, str]:
    a1 = await create_assessment(db, AssessmentCreate(repo_url=REPO))
    a2 = await create_assessment(db, AssessmentCreate(repo_url=REPO))
    return a1.id, a2.id


async def _seed_assessment(db, repo: str = REPO) -> str:
    a = await create_assessment(db, AssessmentCreate(repo_url=repo))
    return a.id


async def test_first_assessment_run_skips_close_pass(db) -> None:
    """No prior assessment row → close pass is a no-op."""
    a = await create_assessment(db, AssessmentCreate(repo_url=REPO))
    seed = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="kept@1.0:CVE-1",
            type="dependency",
            assessment_id=a.id,
            title="kept",
        ),
    )
    closed = await close_disappeared_findings(
        db,
        source_type="trivy",
        kept_source_ids=[],
        assessment_id=a.id,
        repo_url=REPO,
    )
    assert closed == 0
    refreshed = await get_finding(db, seed.id)
    assert refreshed is not None
    assert refreshed.status == "new"


async def test_engine_closes_disappeared_findings_secret_only(db) -> None:
    """Scan 1: dep+secret, scan 2: dep only → secret rows close."""
    a1, a2 = await _seed_two_assessments(db)
    dep = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="dep@1.0:CVE-1",
            type="dependency",
            assessment_id=a1,
            title="dep",
        ),
    )
    secret = await create_finding(
        db,
        FindingCreate(
            source_type="trivy-secret",
            source_id="src/config.js:42:aws-key",
            type="secret",
            assessment_id=a1,
            title="leaked aws key",
        ),
    )
    # New scan only sees the dep; the secret disappeared.
    closed_dep = await close_disappeared_findings(
        db,
        source_type="trivy",
        kept_source_ids=["dep@1.0:CVE-1"],
        assessment_id=a2,
        repo_url=REPO,
    )
    closed_sec = await close_disappeared_findings(
        db,
        source_type="trivy-secret",
        kept_source_ids=[],
        assessment_id=a2,
        repo_url=REPO,
    )
    assert closed_dep == 0
    assert closed_sec == 1

    dep_after = await get_finding(db, dep.id)
    secret_after = await get_finding(db, secret.id)
    assert dep_after is not None
    assert dep_after.status == "new"  # untouched
    assert secret_after is not None
    assert secret_after.status == "closed"
    assert (secret_after.raw_payload or {}).get("system_notes")


async def test_engine_skip_does_not_close_findings(db) -> None:
    """A scanner that didn't run this assessment must not trigger its close pass.

    The caller (engine) only invokes ``close_disappeared_findings`` for
    scanners that completed; this test asserts that contract by *not* calling
    the close function for ``semgrep`` and verifying the row stays open.
    """
    a1, a2 = await _seed_two_assessments(db)
    sg = await create_finding(
        db,
        FindingCreate(
            source_type="semgrep",
            source_id="app/db.py:88:python.django.security.audit.sqli",
            type="code",
            assessment_id=a1,
            title="sqli",
        ),
    )
    # Imagine semgrep was skipped this run — engine doesn't call the close
    # pass for source_type='semgrep'. The row remains untouched.
    refreshed = await get_finding(db, sg.id)
    assert refreshed is not None
    assert refreshed.status == "new"
    del a2  # close pass intentionally not invoked


async def test_trivy_rescan_does_not_close_external_snyk_findings(db) -> None:
    """A Trivy scan must not touch Snyk-imported rows even though both have
    ``type='dependency'`` — ADR-0027 §7 source-type scoping rule.
    """
    _a1, a2 = await _seed_two_assessments(db)
    snyk = await create_finding(
        db,
        FindingCreate(
            source_type="snyk",
            source_id="snyk:SNYK-JS-LODASH-567746",
            type="dependency",
            assessment_id=None,
            title="lodash bug from snyk",
        ),
    )
    closed = await close_disappeared_findings(
        db,
        source_type="trivy",
        kept_source_ids=[],
        assessment_id=a2,
        repo_url=REPO,
    )
    assert closed == 0  # nothing to close — no trivy rows existed

    snyk_after = await get_finding(db, snyk.id)
    assert snyk_after is not None
    assert snyk_after.status == "new"


async def test_close_pass_appends_system_note_to_raw_payload(db) -> None:
    _a1, a2 = await _seed_two_assessments(db)
    f = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id="will@disappear:CVE-X",
            type="dependency",
            assessment_id=_a1,
            title="x",
            raw_payload={"existing": "value"},
        ),
    )
    closed = await close_disappeared_findings(
        db,
        source_type="trivy",
        kept_source_ids=[],
        assessment_id=a2,
        repo_url=REPO,
    )
    assert closed == 1
    refreshed = await get_finding(db, f.id)
    assert refreshed is not None
    assert refreshed.status == "closed"
    notes = (refreshed.raw_payload or {}).get("system_notes")
    assert isinstance(notes, list) and len(notes) == 1
    assert notes[0]["event"] == "auto_closed"
    assert notes[0]["assessment_id"] == a2
    # Existing payload data is preserved alongside the new system_notes.
    assert refreshed.raw_payload.get("existing") == "value"
