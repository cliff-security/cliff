"""Tests for the ``permission_pending`` + ``permission_request`` columns
added in migration ``022_agent_run_permission_pending.sql``.

These columns are the persistence layer of the agent-permission approval
gate. ``executor._handle_permission`` writes them when it parks a
``_PendingApproval`` in memory, and clears them when the asyncio event
resolves (approve / deny / disconnect-auto-deny). ``derive()`` reads
``permission_pending`` off the latest ``remediation_executor`` run to route
the finding into the Review section's "Needs you" bucket.
"""

from __future__ import annotations

from opensec.db.repo_agent_run import (
    create_agent_run,
    get_agent_run,
    reconcile_orphaned_agent_runs,
    update_agent_run,
)
from opensec.db.repo_finding import create_finding
from opensec.db.repo_workspace import create_workspace
from opensec.models import (
    AgentRunCreate,
    AgentRunUpdate,
    FindingCreate,
    WorkspaceCreate,
)


async def _seed_workspace(db) -> str:
    f = await create_finding(
        db, FindingCreate(source_type="trivy", source_id="x", title="x")
    )
    w = await create_workspace(db, WorkspaceCreate(finding_id=f.id))
    return w.id


async def test_new_columns_default_to_pending_false_request_none(db) -> None:
    """A fresh run created via the existing INSERT path picks up the column
    defaults (``permission_pending=0`` / ``permission_request=NULL``)."""
    w_id = await _seed_workspace(db)
    run = await create_agent_run(
        db, w_id, AgentRunCreate(agent_type="remediation_executor", status="running")
    )

    fetched = await get_agent_run(db, run.id)
    assert fetched is not None
    assert fetched.permission_pending is False
    assert fetched.permission_request is None


async def test_round_trip_set_and_clear_pending_permission(db) -> None:
    """The executor sets the marker when it parks ``_PendingApproval`` and
    clears it when the asyncio event resolves. Both transitions must round-
    trip cleanly — and SQLite has no native bool, so we explicitly check the
    underlying integer storage."""
    w_id = await _seed_workspace(db)
    run = await create_agent_run(
        db, w_id, AgentRunCreate(agent_type="remediation_executor", status="running")
    )

    request = {
        "id": "perm-abc",
        "tool": "bash",
        "patterns": ["rm", "-rf", "build/"],
    }
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            permission_pending=True,
            permission_request=request,
        ),
    )

    fetched = await get_agent_run(db, run.id)
    assert fetched is not None
    assert fetched.permission_pending is True
    assert fetched.permission_request == request

    # Raw integer storage guard — SQLite stores booleans as 0/1.
    cursor = await db.execute(
        "SELECT permission_pending FROM agent_run WHERE id = ?", (run.id,)
    )
    row = await cursor.fetchone()
    assert row[0] == 1

    # Clear path (approve/deny resolved).
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(permission_pending=False, permission_request=None),
    )

    cleared = await get_agent_run(db, run.id)
    assert cleared is not None
    assert cleared.permission_pending is False
    assert cleared.permission_request is None

    cursor = await db.execute(
        "SELECT permission_pending, permission_request FROM agent_run "
        "WHERE id = ?",
        (run.id,),
    )
    row = await cursor.fetchone()
    assert row[0] == 0
    assert row[1] is None


async def test_reconcile_clears_pending_permission_on_running_rows(db) -> None:
    """When the backend restarts mid-wait, ``reconcile_orphaned_agent_runs``
    marks the row ``failed``. The pending-permission marker MUST be cleared
    in the same UPDATE so the finding routes to ``review/failed`` (Retry CTA)
    and never to a stale ``awaiting_permission``."""
    w_id = await _seed_workspace(db)
    run = await create_agent_run(
        db, w_id, AgentRunCreate(agent_type="remediation_executor", status="running")
    )
    await update_agent_run(
        db,
        run.id,
        AgentRunUpdate(
            permission_pending=True,
            permission_request={
                "id": "perm-abc",
                "tool": "bash",
                "patterns": ["rm", "-rf", "build/"],
            },
        ),
    )

    updated = await reconcile_orphaned_agent_runs(db)
    assert updated >= 1

    after = await get_agent_run(db, run.id)
    assert after is not None
    assert after.status == "failed"
    assert after.permission_pending is False
    assert after.permission_request is None
