"""OpenAPI schema snapshot test (EXEC-0002 Session 0).

This test freezes the contract surface that every downstream EXEC-0002 session
builds against. If the schema diverges from the committed snapshot, either:

  1) the divergence is intentional — re-run with ``UPDATE_SNAPSHOT=1`` to
     rewrite the snapshot and commit both changes together, or
  2) it's an accidental break — fix the route to match the snapshot.

Keeping the snapshot JSON under version control forces every contract change
to show up in a PR diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from cliff.main import app

SNAPSHOT_PATH = Path(__file__).parent / "openapi_snapshot.json"


def _get_openapi() -> dict[str, Any]:
    # FastAPI computes the schema lazily from the registered routers.
    schema = app.openapi()
    # Drop volatile fields that would cause noisy diffs without changing the
    # contract surface.
    schema.pop("info", None)
    return schema


def test_openapi_snapshot() -> None:
    current = _get_openapi()

    if os.environ.get("UPDATE_SNAPSHOT") == "1" or not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")

    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    assert (
        current == snapshot
    ), "OpenAPI schema drifted from snapshot. Re-run with UPDATE_SNAPSHOT=1 to accept."


def test_new_contract_routes_present() -> None:
    """Every EXEC-0002 route path must be in the schema (sanity check)."""
    schema = _get_openapi()
    paths = set(schema["paths"].keys())
    expected = {
        "/api/onboarding/repo",
        "/api/onboarding/complete",
        "/api/assessment/run",
        "/api/assessment/status/{assessment_id}",
        "/api/assessment/latest",
        "/api/dashboard",
        "/api/posture/fix/{check_name}",
        "/api/completion/{completion_id}/share-action",
    }
    missing = expected - paths
    assert not missing, f"Missing contract-frozen routes: {missing}"


def test_stub_routes_raise_not_implemented() -> None:
    """Sanity check that stubs are wired (body raises NotImplementedError)."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/dashboard")
    # NotImplementedError surfaces as 500 from FastAPI; we just confirm it's
    # not 404 (which would mean the router isn't registered).
    assert response.status_code != 404
