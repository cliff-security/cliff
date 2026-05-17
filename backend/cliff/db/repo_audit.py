"""Repository functions for the audit_log table (append-only, ADR-0017).

Only INSERT operations are supported. UPDATE and DELETE (except retention
cleanup) are intentionally omitted to preserve audit trail integrity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite


async def insert_audit_event(db: aiosqlite.Connection, event: dict[str, Any]) -> int:
    """Insert a single audit event. Returns the new row ID."""
    cursor = await db.execute(
        """
        INSERT INTO audit_log (
            timestamp, event_type, actor_type, actor_id,
            workspace_id, integration_id, provider_name,
            tool_name, verb, action_tier, status,
            duration_ms, parameters_hash, error_message,
            correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["timestamp"],
            event["event_type"],
            event.get("actor_type", "user"),
            event.get("actor_id"),
            event.get("workspace_id"),
            event.get("integration_id"),
            event.get("provider_name"),
            event.get("tool_name"),
            event.get("verb"),
            event.get("action_tier", 0),
            event["status"],
            event.get("duration_ms"),
            event.get("parameters_hash"),
            event.get("error_message"),
            event.get("correlation_id"),
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def query_audit_log(
    db: aiosqlite.Connection,
    *,
    workspace_id: str | None = None,
    integration_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    correlation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query audit events with optional filters. Returns newest first."""
    conditions: list[str] = []
    params: list[Any] = []

    if workspace_id:
        conditions.append("workspace_id = ?")
        params.append(workspace_id)
    if integration_id:
        conditions.append("integration_id = ?")
        params.append(integration_id)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if until:
        conditions.append("timestamp <= ?")
        params.append(until)
    if correlation_id:
        conditions.append("correlation_id = ?")
        params.append(correlation_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    cursor = await db.execute(
        f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",  # noqa: S608
        params,
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def count_audit_events(
    db: aiosqlite.Connection,
    *,
    workspace_id: str | None = None,
    integration_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> int:
    """Count audit events matching filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if workspace_id:
        conditions.append("workspace_id = ?")
        params.append(workspace_id)
    if integration_id:
        conditions.append("integration_id = ?")
        params.append(integration_id)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if until:
        conditions.append("timestamp <= ?")
        params.append(until)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM audit_log {where}",  # noqa: S608
        params,
    )
    row = await cursor.fetchone()
    return row[0]


async def cleanup_old_events(db: aiosqlite.Connection, retention_days: int = 90) -> int:
    """Delete audit events older than *retention_days*. Returns count deleted."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    cursor = await db.execute(
        "DELETE FROM audit_log WHERE timestamp < ?", (cutoff,)
    )
    await db.commit()
    return cursor.rowcount
