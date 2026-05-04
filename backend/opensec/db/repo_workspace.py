"""Repository functions for the Workspace entity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from opensec.models import Workspace, WorkspaceCreate, WorkspaceUpdate

if TYPE_CHECKING:
    import aiosqlite


def _row_to_workspace(row: aiosqlite.Row) -> Workspace:
    # ``repo_url`` is migration 013 — older rows / mocked rows may not expose
    # the column, so read defensively and fall back to ``None``.
    try:
        repo_url = row["repo_url"]
    except (IndexError, KeyError):
        repo_url = None
    return Workspace(
        id=row["id"],
        finding_id=row["finding_id"],
        kind=row["kind"],
        source_check_name=row["source_check_name"],
        state=row["state"],
        current_focus=row["current_focus"],
        active_plan_version=row["active_plan_version"],
        linked_ticket_id=row["linked_ticket_id"],
        validation_state=row["validation_state"],
        workspace_dir=row["workspace_dir"],
        context_version=row["context_version"],
        repo_url=repo_url,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_workspace(db: aiosqlite.Connection, data: WorkspaceCreate) -> Workspace:
    workspace_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO workspace
            (id, finding_id, state, current_focus, active_plan_version,
             linked_ticket_id, validation_state, repo_url,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workspace_id,
            data.finding_id,
            data.state,
            data.current_focus,
            None,
            None,
            None,
            data.repo_url,
            now,
            now,
        ),
    )
    await db.commit()
    return await get_workspace(db, workspace_id)  # type: ignore[return-value]


async def get_workspace(db: aiosqlite.Connection, workspace_id: str) -> Workspace | None:
    cursor = await db.execute("SELECT * FROM workspace WHERE id = ?", (workspace_id,))
    row = await cursor.fetchone()
    return _row_to_workspace(row) if row else None


async def list_workspaces(
    db: aiosqlite.Connection,
    *,
    state: str | None = None,
    finding_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Workspace]:
    conditions: list[str] = []
    params: list[str | int] = []
    if state:
        conditions.append("state = ?")
        params.append(state)
    if finding_id:
        conditions.append("finding_id = ?")
        params.append(finding_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])
    cursor = await db.execute(
        f"SELECT * FROM workspace {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",  # noqa: S608
        params,
    )
    return [_row_to_workspace(row) for row in await cursor.fetchall()]


async def list_workspaces_by_finding_ids(
    db: aiosqlite.Connection, finding_ids: list[str]
) -> dict[str, Workspace]:
    """Return ``{finding_id: most_recent_workspace}`` for the given findings.

    IMPL-0006 batch helper. ``finding_id`` is unique-per-row in practice, but
    if duplicates exist (e.g. an old workspace was never deleted before a new
    one was created), the most recently updated wins so the derivation reads
    the live workspace state. Findings with no workspace are absent from the
    returned mapping.
    """
    if not finding_ids:
        return {}
    placeholders = ",".join("?" for _ in finding_ids)
    cursor = await db.execute(
        f"SELECT * FROM workspace WHERE finding_id IN ({placeholders})"  # noqa: S608
        " ORDER BY updated_at DESC",
        finding_ids,
    )
    by_finding: dict[str, Workspace] = {}
    for row in await cursor.fetchall():
        ws = _row_to_workspace(row)
        # First match wins (rows are ordered by updated_at DESC).
        if ws.finding_id and ws.finding_id not in by_finding:
            by_finding[ws.finding_id] = ws
    return by_finding


async def update_workspace(
    db: aiosqlite.Connection, workspace_id: str, data: WorkspaceUpdate
) -> Workspace | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_workspace(db, workspace_id)

    fields["updated_at"] = datetime.now(UTC).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), workspace_id]

    await db.execute(f"UPDATE workspace SET {set_clause} WHERE id = ?", values)  # noqa: S608
    await db.commit()
    return await get_workspace(db, workspace_id)


async def delete_workspace(db: aiosqlite.Connection, workspace_id: str) -> bool:
    cursor = await db.execute("DELETE FROM workspace WHERE id = ?", (workspace_id,))
    await db.commit()
    return cursor.rowcount > 0


async def update_workspace_dir(
    db: aiosqlite.Connection, workspace_id: str, workspace_dir: str
) -> None:
    """Set the workspace_dir path. Called once after directory creation."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET workspace_dir = ?, updated_at = ? WHERE id = ?",
        (workspace_dir, now, workspace_id),
    )
    await db.commit()


async def create_repo_action_workspace(
    db: aiosqlite.Connection,
    *,
    workspace_id: str,
    kind: str,
    source_check_name: str,
    workspace_dir: str | None = None,
    state: str = "pending",
) -> None:
    """Insert a repo-action workspace row (PRD-0004 / ADR-0030).

    Unlike ``create_workspace()`` this is called by the posture-fix spawner
    after the filesystem scaffolding is in place. ``finding_id`` is NULL and
    ``source_check_name`` carries the natural key (``security_md`` /
    ``dependabot_config``) so the partial unique index
    ``idx_workspace_active_per_check`` can enforce at-most-one-active-per-check.

    Raises ``IntegrityError`` (via aiosqlite) when a second concurrent insert
    collides with a non-terminal workspace for the same check. The caller
    (``POST /api/posture/fix/{check_name}``) catches this and returns 409.
    """
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO workspace
            (id, finding_id, state, kind, source_check_name,
             workspace_dir, current_focus, active_plan_version,
             linked_ticket_id, validation_state, created_at, updated_at)
        VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (workspace_id, state, kind, source_check_name, workspace_dir, now, now),
    )
    await db.commit()


async def set_workspace_state(
    db: aiosqlite.Connection, workspace_id: str, state: str
) -> None:
    """UPDATE ``workspace.state`` for the given id.

    Called by the repo-action runner on terminal transitions so the partial
    unique index ``idx_workspace_active_per_check`` releases and a retry of
    the same posture check can succeed (PRD-0004 Story 3).
    """
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET state = ?, updated_at = ? WHERE id = ?",
        (state, now, workspace_id),
    )
    await db.commit()


async def get_active_workspace_by_source_check_name(
    db: aiosqlite.Connection, check_name: str
) -> Workspace | None:
    """Return the single non-terminal workspace for a posture check, if any.

    Uses the same predicate as the partial unique index so "active" here
    means the one row that caused an INSERT to collide. When no active
    workspace exists (e.g. after a terminal transition), returns None.
    """
    cursor = await db.execute(
        """
        SELECT * FROM workspace
        WHERE source_check_name = ?
          AND state IN ('pending', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (check_name,),
    )
    row = await cursor.fetchone()
    return _row_to_workspace(row) if row else None


async def increment_context_version(
    db: aiosqlite.Connection, workspace_id: str
) -> int:
    """Atomically increment context_version. Returns the new version."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE workspace SET context_version = context_version + 1, updated_at = ? WHERE id = ?",
        (now, workspace_id),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT context_version FROM workspace WHERE id = ?", (workspace_id,)
    )
    row = await cursor.fetchone()
    return row["context_version"] if row else 0
