"""Tests for the PRD-0006 Phase 2 reject endpoint (IMPL-0007 §B3).

``POST /findings/{id}/reject`` flips ``Finding.status`` to ``exception`` and
persists the user's reason + optional note. Re-rejecting the same finding
overrides the prior reason+note (correctability over append-only history).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def finding_payload():
    return {
        "source_type": "tenable",
        "source_id": "vuln-001",
        "title": "CVE-2024-1234 in libfoo",
        "raw_severity": "high",
    }


async def _create(db_client, finding_payload, **overrides):
    payload = {**finding_payload, **overrides}
    resp = await db_client.post("/api/findings", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_reject_happy_path(db_client, finding_payload) -> None:
    finding = await _create(db_client, finding_payload)
    resp = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "false_positive", "note": "Triaged by sec-team."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "exception"
    assert body["exception_reason"] == "false_positive"
    assert body["exception_note"] == "Triaged by sec-team."
    # Derived stage now reflects the verdict.
    assert body["derived"]["section"] == "done"
    assert body["derived"]["stage"] == "false_positive"


async def test_reject_without_note(db_client, finding_payload) -> None:
    finding = await _create(db_client, finding_payload)
    resp = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "wont_fix"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exception_reason"] == "wont_fix"
    assert body["exception_note"] is None
    assert body["derived"]["stage"] == "wont_fix"


async def test_reject_missing_reason_returns_422(db_client, finding_payload) -> None:
    finding = await _create(db_client, finding_payload)
    resp = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"note": "missing reason field"},
    )
    assert resp.status_code == 422


async def test_reject_invalid_reason_returns_422(db_client, finding_payload) -> None:
    finding = await _create(db_client, finding_payload)
    resp = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "i_just_dont_like_it"},
    )
    assert resp.status_code == 422


async def test_reject_note_over_280_chars_returns_422(
    db_client, finding_payload
) -> None:
    finding = await _create(db_client, finding_payload)
    resp = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "deferred", "note": "x" * 281},
    )
    assert resp.status_code == 422


async def test_reject_unknown_finding_returns_404(db_client) -> None:
    resp = await db_client.post(
        "/api/findings/does-not-exist/reject",
        json={"reason": "false_positive"},
    )
    assert resp.status_code == 404


async def test_reject_overrides_prior_reason_and_note(
    db_client, finding_payload
) -> None:
    finding = await _create(db_client, finding_payload)
    first = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "false_positive", "note": "first take"},
    )
    assert first.status_code == 200

    second = await db_client.post(
        f"/api/findings/{finding['id']}/reject",
        json={"reason": "wont_fix", "note": "actually we'll skip this"},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["exception_reason"] == "wont_fix"
    assert body["exception_note"] == "actually we'll skip this"
    assert body["derived"]["stage"] == "wont_fix"
