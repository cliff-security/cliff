"""Repository functions for the AgentRun entity."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import AgentRun, AgentRunCreate, AgentRunUpdate

if TYPE_CHECKING:
    import aiosqlite

_JSON_FIELDS = {
    "input_json",
    "evidence_json",
    "structured_output",
    "permission_request",
}


def _row_to_agent_run(row: aiosqlite.Row) -> AgentRun:
    return AgentRun(
        id=row["id"],
        workspace_id=row["workspace_id"],
        agent_type=row["agent_type"],
        status=row["status"],
        input_json=json.loads(row["input_json"]) if row["input_json"] else None,
        summary_markdown=row["summary_markdown"],
        confidence=row["confidence"],
        evidence_json=json.loads(row["evidence_json"]) if row["evidence_json"] else None,
        structured_output=(
            json.loads(row["structured_output"]) if row["structured_output"] else None
        ),
        next_action_hint=row["next_action_hint"],
        last_error=row["last_error"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        permission_pending=bool(row["permission_pending"]),
        permission_request=(
            json.loads(row["permission_request"]) if row["permission_request"] else None
        ),
    )


async def create_agent_run(
    db: aiosqlite.Connection, workspace_id: str, data: AgentRunCreate
) -> AgentRun:
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    started = now if data.status == "running" else None
    await db.execute(
        """
        INSERT INTO agent_run
            (id, workspace_id, agent_type, status, input_json, started_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            workspace_id,
            data.agent_type,
            data.status,
            json.dumps(data.input_json) if data.input_json is not None else None,
            started,
        ),
    )
    await db.commit()
    return await get_agent_run(db, run_id)  # type: ignore[return-value]


async def get_agent_run(db: aiosqlite.Connection, run_id: str) -> AgentRun | None:
    cursor = await db.execute("SELECT * FROM agent_run WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    return _row_to_agent_run(row) if row else None


async def list_agent_runs(
    db: aiosqlite.Connection,
    workspace_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[AgentRun]:
    cursor = await db.execute(
        "SELECT * FROM agent_run WHERE workspace_id = ?"
        " ORDER BY started_at DESC NULLS LAST LIMIT ? OFFSET ?",
        (workspace_id, limit, offset),
    )
    return [_row_to_agent_run(row) for row in await cursor.fetchall()]


async def list_latest_runs_by_workspace_ids(
    db: aiosqlite.Connection, workspace_ids: list[str]
) -> dict[str, dict[str, AgentRun]]:
    """Return ``{workspace_id: {agent_type: most_recent_run}}``.

    IMPL-0006 batch helper. The most recent run per (workspace, agent_type)
    pair is what the derivation function reads. Older runs are dropped from
    the mapping. Workspaces with no runs are absent.
    """
    if not workspace_ids:
        return {}
    placeholders = ",".join("?" for _ in workspace_ids)
    cursor = await db.execute(
        f"SELECT * FROM agent_run WHERE workspace_id IN ({placeholders})"  # noqa: S608
        " ORDER BY started_at DESC NULLS LAST",
        workspace_ids,
    )
    out: dict[str, dict[str, AgentRun]] = {}
    for row in await cursor.fetchall():
        run = _row_to_agent_run(row)
        bucket = out.setdefault(run.workspace_id, {})
        # First write wins (rows are sorted newest-first).
        bucket.setdefault(run.agent_type, run)
    return out


async def update_agent_run(
    db: aiosqlite.Connection, run_id: str, data: AgentRunUpdate
) -> AgentRun | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_agent_run(db, run_id)

    now = datetime.now(UTC).isoformat()

    # Auto-set timestamps based on status transitions.
    if "status" in fields:
        if fields["status"] == "running":
            fields["started_at"] = now
        elif fields["status"] in ("completed", "failed", "cancelled", "rate_limited"):
            fields["completed_at"] = now

    # Serialize JSON fields.
    for key in _JSON_FIELDS:
        if key in fields and fields[key] is not None:
            fields[key] = json.dumps(fields[key])

    # SQLite has no native bool — coerce permission_pending to 0/1 so the
    # CHECK constraint on migration 022 stays happy.
    if "permission_pending" in fields and fields["permission_pending"] is not None:
        fields["permission_pending"] = int(bool(fields["permission_pending"]))

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), run_id]

    await db.execute(f"UPDATE agent_run SET {set_clause} WHERE id = ?", values)  # noqa: S608
    await db.commit()
    return await get_agent_run(db, run_id)


async def get_pa_message_history(
    db: aiosqlite.Connection, run_id: str
) -> str | None:
    """Read the stored PA message-history JSON for a paused executor run.

    Kept off the API-facing :class:`AgentRun` model (the blob is large and
    internal); the resume path reads it directly to rebuild the agent's
    conversation via ``agent.run(message_history=...)``.
    """
    cursor = await db.execute(
        "SELECT pa_message_history FROM agent_run WHERE id = ?", (run_id,)
    )
    row = await cursor.fetchone()
    return row["pa_message_history"] if row else None


async def reconcile_orphaned_agent_runs(db: aiosqlite.Connection) -> int:
    """Mark ``queued``/``running`` rows as ``failed`` at startup.

    The asyncio task that drives each ``queued``/``running`` row lives inside
    the backend process — when uvicorn reloads (or the process crashes)
    every in-flight task dies but the DB row is left mid-execution.
    Without this, the issue-derivation returns ``stage='generating'`` (or
    similar) forever, the sidebar spins on "Thinking…", and the user has
    no path to recover short of running raw SQL.

    Mirrors :func:`cliff.db.dao.assessment.reconcile_orphaned_assessments`
    for the agent_run table. Idempotent — returns the number of rows updated.
    """
    now_iso = datetime.now(UTC).isoformat()
    interrupted_msg = (
        "**Agent run interrupted.** The backend restarted while this agent "
        "was working. Click Approve / Start to retry."
    )
    # Also clear the agent-permission marker — if the backend died while a
    # ``_PendingApproval`` was parked, the row will come back as ``failed``
    # and must route to the existing ``failed`` stage (Retry CTA), never to
    # a stale ``awaiting_permission``.
    cursor = await db.execute(
        """
        UPDATE agent_run
           SET status = 'failed',
               completed_at = COALESCE(completed_at, ?),
               summary_markdown = COALESCE(summary_markdown, ?),
               permission_pending = 0,
               permission_request = NULL,
               pa_message_history = NULL
         WHERE status IN ('queued', 'running')
        """,
        (now_iso, interrupted_msg),
    )
    await db.commit()
    return cursor.rowcount
