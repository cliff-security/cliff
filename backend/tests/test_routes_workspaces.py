"""Tests for Workspace CRUD endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opensec.db.repo_finding import mark_started_on_workspace_create
from opensec.db.repo_workspace import create_workspace as raw_create_workspace
from opensec.db.repo_workspace import delete_workspace as raw_delete_workspace
from opensec.models import WorkspaceCreate


@pytest.fixture
async def finding_id(db_client):
    """Create a finding and return its ID (workspaces need a valid finding_id FK)."""
    resp = await db_client.post(
        "/api/findings",
        json={"source_type": "test", "source_id": "f-1", "title": "Test finding"},
    )
    return resp.json()["id"]


@pytest.fixture(autouse=True)
async def _configure_mock_builder(db_client):
    """Configure the mock context_builder to delegate to raw DB functions.

    The POST /api/workspaces route now calls context_builder.create_workspace()
    instead of the raw repo function. The mock must create a real DB row so
    the rest of the test can read/update/delete it.
    """
    from opensec.main import app

    async def _mock_create(db, finding, **_kwargs):
        data = WorkspaceCreate(finding_id=finding.id)
        ws = await raw_create_workspace(db, data)
        # Mirror the real context_builder behaviour (PRD-0006 / IMPL-0006):
        # creating a workspace flips Finding.status new/triaged → in_progress.
        await mark_started_on_workspace_create(db, finding.id)
        return ws

    async def _mock_delete(db, workspace_id):
        return await raw_delete_workspace(db, workspace_id)

    # Also make create_workspace accept a Finding model (fetched from DB)
    async def _mock_create_from_route(db, finding, **kwargs):
        # The route passes a Finding model; create the workspace
        return await _mock_create(db, finding, **kwargs)

    mock_builder = app.state.context_builder
    mock_builder.create_workspace = AsyncMock(side_effect=_mock_create_from_route)
    mock_builder.delete_workspace = AsyncMock(side_effect=_mock_delete)


async def test_create_workspace(db_client, finding_id):
    resp = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    assert resp.status_code == 201
    data = resp.json()
    assert data["finding_id"] == finding_id
    assert data["state"] == "open"
    assert data["id"]


async def test_create_workspace_finding_not_found(db_client):
    resp = await db_client.post("/api/workspaces", json={"finding_id": "nonexistent"})
    assert resp.status_code == 404


async def test_resolve_workspace_flips_finding_to_validated(db_client, finding_id):
    """PRD-0006 Story 5 — clicking Resolve on the workspace flips the linked
    finding to validated so it visibly moves into the Done section.

    Phase-1 stand-in for the validator until webhook-driven auto-validation
    lands.
    """
    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()
    # Sanity: finding is in_progress after workspace creation (prior fix).
    pre = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert pre["status"] == "in_progress"

    resp = await db_client.patch(
        f"/api/workspaces/{ws['id']}", json={"state": "closed"}
    )
    assert resp.status_code == 200

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "validated"
    assert post["derived"]["section"] == "done"
    assert post["derived"]["stage"] == "fixed"


async def test_resolve_workspace_does_not_flip_for_non_terminal_state(
    db_client, finding_id
):
    """Updating workspace state to e.g. ``waiting`` must NOT mark the finding
    as resolved — only ``state='closed'`` triggers the flip."""
    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()

    resp = await db_client.patch(
        f"/api/workspaces/{ws['id']}", json={"state": "waiting"}
    )
    assert resp.status_code == 200

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "in_progress"  # unchanged from the create-flip
    assert post["derived"]["section"] != "done"


async def test_resolve_workspace_idempotent_on_already_done_finding(
    db_client, finding_id
):
    """Re-resolving a workspace whose finding is already in a terminal state
    must not silently re-categorise it (e.g. an exception/false_positive
    decision must survive)."""
    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()
    # Mark the finding as a false-positive exception via the existing route.
    await db_client.patch(
        f"/api/findings/{finding_id}",
        json={"status": "exception", "raw_payload": {"exception_reason": "false_positive"}},
    )

    await db_client.patch(f"/api/workspaces/{ws['id']}", json={"state": "closed"})

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "exception"  # NOT overwritten
    assert post["derived"]["stage"] == "false_positive"


async def test_resolve_workspace_http_reconciles_pr_url_from_executor_run(
    db_client, finding_id
):
    """EF-B14 HTTP-level — PATCH /api/workspaces state=closed must reconcile
    Finding.pr_url from the latest remediation_executor AgentRun before the
    response returns, so the UI sees the link instead of pr_url=null."""
    import opensec.db.connection as conn_module
    from opensec.db.repo_agent_run import create_agent_run, update_agent_run
    from opensec.models import AgentRunCreate, AgentRunUpdate

    pr_url = "https://github.com/cliff-security/NodeGoat/pull/6"

    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()

    # Seed a completed remediation_executor run whose structured_output
    # carries the pr_url. This mirrors what AgentExecutor writes after the
    # PR-verification step succeeds.
    db = conn_module._db
    assert db is not None
    run = await create_agent_run(
        db, ws["id"], AgentRunCreate(agent_type="remediation_executor")
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            status="completed",
            summary_markdown="opened pr",
            confidence=0.9,
            structured_output={"status": "pr_created", "pr_url": pr_url},
        ),
    )

    # Sanity: before close, Finding.pr_url is null (legacy orphan path).
    pre = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert pre["pr_url"] is None

    resp = await db_client.patch(
        f"/api/workspaces/{ws['id']}", json={"state": "closed"}
    )
    assert resp.status_code == 200

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "validated"
    assert post["pr_url"] == pr_url, (
        "PATCH /api/workspaces state=closed must reconcile pr_url from the "
        "latest remediation_executor AgentRun before flipping the finding."
    )


async def test_resolve_workspace_http_close_with_no_executor_run_leaves_pr_url_null(
    db_client, finding_id,
):
    """Posture finding (no executor ever ran) — close still flips status,
    pr_url stays null. The fix must not break this path."""
    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()

    resp = await db_client.patch(
        f"/api/workspaces/{ws['id']}", json={"state": "closed"}
    )
    assert resp.status_code == 200

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "validated"
    assert post["pr_url"] is None


async def test_resolve_workspace_http_does_not_clobber_user_supplied_pr_url(
    db_client, finding_id,
):
    """If a user explicitly set pr_url via PATCH /api/findings/{id}, the
    close-handler's reconciliation must not overwrite it with a stale URL
    from an old AgentRun."""
    import opensec.db.connection as conn_module
    from opensec.db.repo_agent_run import create_agent_run, update_agent_run
    from opensec.models import AgentRunCreate, AgentRunUpdate

    user_url = "https://github.com/example/repo/pull/42"
    stale_url = "https://github.com/example/repo/pull/1"

    ws = (
        await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ).json()

    # User explicitly sets pr_url via the finding-update route.
    await db_client.patch(
        f"/api/findings/{finding_id}", json={"pr_url": user_url}
    )

    # Stale executor run carrying a different URL.
    db = conn_module._db
    assert db is not None
    run = await create_agent_run(
        db, ws["id"], AgentRunCreate(agent_type="remediation_executor")
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            status="completed",
            structured_output={"status": "pr_created", "pr_url": stale_url},
        ),
    )

    resp = await db_client.patch(
        f"/api/workspaces/{ws['id']}", json={"state": "closed"}
    )
    assert resp.status_code == 200

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["pr_url"] == user_url, (
        "User-supplied pr_url must survive close-handler reconciliation."
    )


async def test_create_workspace_flips_finding_to_in_progress(db_client, finding_id):
    """PRD-0006 Story 2 / IMPL-0006 root-cause fix.

    Clicking Start on a Todo row creates a workspace AND flips the finding's
    status so the row visibly leaves Todo immediately, instead of waiting
    for the first agent run to update Finding.status.
    """
    # Sanity check the seed status.
    pre = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert pre["status"] == "new"

    resp = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    assert resp.status_code == 201

    post = (await db_client.get(f"/api/findings/{finding_id}")).json()
    assert post["status"] == "in_progress"
    # Derived projection should also flip out of Todo.
    assert post["derived"]["section"] != "todo"


async def test_list_workspaces(db_client, finding_id):
    # POST /workspaces is idempotent per finding (one workspace per finding,
    # forever — preserves KB + agent runs + sidebar state). A second POST
    # returns the existing workspace with status 200; only the first is 201.
    first = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    assert first.status_code == 201
    second = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    resp = await db_client.get("/api/workspaces")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_list_workspaces_filter_by_state(db_client, finding_id):
    await db_client.post("/api/workspaces", json={"finding_id": finding_id})

    resp = await db_client.get("/api/workspaces", params={"state": "open"})
    assert len(resp.json()) == 1

    resp = await db_client.get("/api/workspaces", params={"state": "closed"})
    assert len(resp.json()) == 0


async def test_list_workspaces_filter_by_finding(db_client, finding_id):
    await db_client.post("/api/workspaces", json={"finding_id": finding_id})

    resp = await db_client.get("/api/workspaces", params={"finding_id": finding_id})
    assert len(resp.json()) == 1

    resp = await db_client.get("/api/workspaces", params={"finding_id": "nonexistent"})
    assert len(resp.json()) == 0


async def test_get_workspace(db_client, finding_id):
    create_resp = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ws_id = create_resp.json()["id"]

    resp = await db_client.get(f"/api/workspaces/{ws_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == ws_id


async def test_get_workspace_not_found(db_client):
    resp = await db_client.get("/api/workspaces/nonexistent")
    assert resp.status_code == 404


async def test_update_workspace(db_client, finding_id):
    create_resp = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ws_id = create_resp.json()["id"]

    resp = await db_client.patch(
        f"/api/workspaces/{ws_id}",
        json={"state": "waiting", "current_focus": "enrichment"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "waiting"
    assert data["current_focus"] == "enrichment"


async def test_delete_workspace(db_client, finding_id):
    create_resp = await db_client.post("/api/workspaces", json={"finding_id": finding_id})
    ws_id = create_resp.json()["id"]

    resp = await db_client.delete(f"/api/workspaces/{ws_id}")
    assert resp.status_code == 204

    resp = await db_client.get(f"/api/workspaces/{ws_id}")
    assert resp.status_code == 404
