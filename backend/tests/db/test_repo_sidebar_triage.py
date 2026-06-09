"""The sidebar_state.triage column persists + round-trips (migration 024).

ADR-0051 §5: ``SidebarState.triage`` is a new top-level section. The store is
columnar (one JSON column per section), so this verifies the column added by
migration 024 actually persists and reads back, and stays disjoint from the
``evidence`` section.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cliff.db.connection import close_db, init_db
from cliff.db.repo_sidebar import get_sidebar, upsert_sidebar
from cliff.models import SidebarStateUpdate


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    # sidebar_state.workspace_id FK → workspace(id); create the parent row.
    now = datetime.now(UTC).isoformat()
    await conn.execute(
        "INSERT INTO workspace (id, created_at, updated_at) VALUES ('ws-1', ?, ?)",
        (now, now),
    )
    await conn.commit()
    yield conn
    await close_db()


async def test_triage_section_round_trips(db) -> None:
    triage = {
        "verdict": "unexploitable",
        "confidence": 0.9,
        "recommended_close": "unexploitable",
        "reachability": {"reached": False, "path": [], "summary": "No path found."},
        "checks": [{"eyebrow": "REACHABILITY", "result": "No path", "kind": "pass"}],
    }
    await upsert_sidebar(
        db,
        "ws-1",
        SidebarStateUpdate(evidence={"reachable": "no"}, triage=triage),
    )
    sb = await get_sidebar(db, "ws-1")
    assert sb is not None
    assert sb.triage == triage
    # Disjoint from evidence.
    assert sb.evidence == {"reachable": "no"}


async def test_triage_section_overwrites_on_rerun(db) -> None:
    """A re-run overwrites sidebar.triage (idempotent re-triage)."""
    await upsert_sidebar(
        db, "ws-1", SidebarStateUpdate(triage={"verdict": "needs_review", "confidence": 0.4})
    )
    await upsert_sidebar(
        db, "ws-1", SidebarStateUpdate(triage={"verdict": "real", "confidence": 0.95})
    )
    sb = await get_sidebar(db, "ws-1")
    assert sb is not None
    assert sb.triage is not None
    assert sb.triage["verdict"] == "real"
    assert sb.triage["confidence"] == 0.95
