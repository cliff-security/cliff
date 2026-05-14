"""V14 — DB-level workspace state-leak test.

Closes the schema-level boundary on the workspace-isolation promise. ADR-0014
covers *process* isolation; this suite covers *data* isolation: two workspaces
opened against two different findings must never read each other's rows in
``sidebar_state``, ``message``, ``agent_run``, or ``ticket_link``.

A workspace data leak in a security tool is a trust-collapse bug — these are P0
invariants, hence a deterministic pytest that runs on every CI build rather than
a one-off QA session.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from opensec.db.repo_agent_run import create_agent_run, list_agent_runs
from opensec.db.repo_finding import create_finding
from opensec.db.repo_message import create_message, list_messages
from opensec.db.repo_sidebar import get_sidebar, upsert_sidebar
from opensec.db.repo_workspace import create_workspace
from opensec.models import (
    AgentRunCreate,
    FindingCreate,
    MessageCreate,
    SidebarStateUpdate,
    Workspace,
    WorkspaceCreate,
)

if TYPE_CHECKING:
    import aiosqlite


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_workspace(db: aiosqlite.Connection, label: str) -> Workspace:
    """Create a distinct finding + workspace pair. ``label`` keeps the
    ``(source_type, source_id)`` UPSERT key unique so each call is a fresh row.
    """
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="trivy",
            source_id=f"src-{label}",
            title=f"Finding {label}",
        ),
    )
    return await create_workspace(db, WorkspaceCreate(finding_id=finding.id))


async def _insert_ticket_link(
    db: aiosqlite.Connection, workspace_id: str, external_key: str
) -> str:
    """Insert a ``ticket_link`` row directly.

    ``ticket_link`` has no repository layer yet (no production read/write path),
    so this suite exercises the table at the schema level: foreign key +
    ``workspace_id`` column. The raw INSERT here mirrors what a future
    ``repo_ticket_link`` would do.
    """
    ticket_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO ticket_link
            (id, workspace_id, provider, external_key, title, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ticket_id, workspace_id, "jira", external_key, f"Ticket {external_key}", "open"),
    )
    await db.commit()
    return ticket_id


async def _list_ticket_links(
    db: aiosqlite.Connection, *, workspace_id: str
) -> list[aiosqlite.Row]:
    """Scoped read of ``ticket_link`` — the ``workspace_id`` kwarg is mandatory,
    mirroring the repo-layer convention for the other three tables.
    """
    cursor = await db.execute(
        "SELECT * FROM ticket_link WHERE workspace_id = ?", (workspace_id,)
    )
    return list(await cursor.fetchall())


# ---------------------------------------------------------------------------
# Per-entity isolation
# ---------------------------------------------------------------------------


async def test_two_workspaces_cannot_see_each_others_sidebar_state(
    db: aiosqlite.Connection,
) -> None:
    ws_a = await _make_workspace(db, "A")
    ws_b = await _make_workspace(db, "B")

    await upsert_sidebar(
        db, ws_a.id, SidebarStateUpdate(summary={"text": "summary A"})
    )
    await upsert_sidebar(
        db, ws_b.id, SidebarStateUpdate(summary={"text": "summary B"})
    )

    a_state = await get_sidebar(db, ws_a.id)
    b_state = await get_sidebar(db, ws_b.id)

    assert a_state is not None
    assert b_state is not None
    # Each workspace sees only its own row.
    assert a_state.workspace_id == ws_a.id
    assert b_state.workspace_id == ws_b.id
    # No content from A appears in B's view, and vice versa.
    assert a_state.summary == {"text": "summary A"}
    assert b_state.summary == {"text": "summary B"}


async def test_message_isolation(db: aiosqlite.Connection) -> None:
    ws_a = await _make_workspace(db, "A")
    ws_b = await _make_workspace(db, "B")

    await create_message(
        db, ws_a.id, MessageCreate(role="user", content_markdown="message A")
    )
    await create_message(
        db, ws_b.id, MessageCreate(role="user", content_markdown="message B")
    )

    a_messages = await list_messages(db, ws_a.id)
    b_messages = await list_messages(db, ws_b.id)

    assert {m.workspace_id for m in a_messages} == {ws_a.id}
    assert {m.workspace_id for m in b_messages} == {ws_b.id}

    a_content = {m.content_markdown for m in a_messages}
    b_content = {m.content_markdown for m in b_messages}
    assert "message B" not in a_content
    assert "message A" not in b_content


async def test_agent_run_isolation(db: aiosqlite.Connection) -> None:
    ws_a = await _make_workspace(db, "A")
    ws_b = await _make_workspace(db, "B")

    await create_agent_run(
        db, ws_a.id, AgentRunCreate(agent_type="finding_enricher", input_json={"ws": "A"})
    )
    await create_agent_run(
        db, ws_b.id, AgentRunCreate(agent_type="finding_enricher", input_json={"ws": "B"})
    )

    a_runs = await list_agent_runs(db, ws_a.id)
    b_runs = await list_agent_runs(db, ws_b.id)

    assert {r.workspace_id for r in a_runs} == {ws_a.id}
    assert {r.workspace_id for r in b_runs} == {ws_b.id}

    a_inputs = {(r.input_json or {}).get("ws") for r in a_runs}
    b_inputs = {(r.input_json or {}).get("ws") for r in b_runs}
    assert "B" not in a_inputs
    assert "A" not in b_inputs


async def test_ticket_link_isolation(db: aiosqlite.Connection) -> None:
    ws_a = await _make_workspace(db, "A")
    ws_b = await _make_workspace(db, "B")

    await _insert_ticket_link(db, ws_a.id, external_key="JIRA-A")
    await _insert_ticket_link(db, ws_b.id, external_key="JIRA-B")

    a_tickets = await _list_ticket_links(db, workspace_id=ws_a.id)
    b_tickets = await _list_ticket_links(db, workspace_id=ws_b.id)

    assert {t["workspace_id"] for t in a_tickets} == {ws_a.id}
    assert {t["workspace_id"] for t in b_tickets} == {ws_b.id}

    a_keys = {t["external_key"] for t in a_tickets}
    b_keys = {t["external_key"] for t in b_tickets}
    assert "JIRA-B" not in a_keys
    assert "JIRA-A" not in b_keys


# ---------------------------------------------------------------------------
# Belt-and-suspenders — no query path leaks rows without workspace_id scoping
# ---------------------------------------------------------------------------


async def test_sidebar_query_without_workspace_id_raises(
    db: aiosqlite.Connection,
) -> None:
    """``get_sidebar`` cannot be called without a ``workspace_id`` — the
    parameter is positional-required, so a forgetful caller fails loudly
    instead of silently reading global data.
    """
    with pytest.raises(TypeError):
        await get_sidebar(db)  # type: ignore[call-arg]


async def test_message_query_without_workspace_id_raises(
    db: aiosqlite.Connection,
) -> None:
    with pytest.raises(TypeError):
        await list_messages(db)  # type: ignore[call-arg]


async def test_agent_run_query_without_workspace_id_raises(
    db: aiosqlite.Connection,
) -> None:
    with pytest.raises(TypeError):
        await list_agent_runs(db)  # type: ignore[call-arg]


async def test_ticket_link_query_without_workspace_id_raises(
    db: aiosqlite.Connection,
) -> None:
    """``ticket_link`` has no repository layer; the scoped read helper used by
    this suite makes ``workspace_id`` a required keyword-only argument so the
    same belt-and-suspenders guarantee holds the day a real repo is added.
    """
    with pytest.raises(TypeError):
        await _list_ticket_links(db)  # type: ignore[call-arg]
