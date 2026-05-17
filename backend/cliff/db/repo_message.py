"""Repository functions for the Message entity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import Message, MessageCreate

if TYPE_CHECKING:
    import aiosqlite


def _row_to_message(row: aiosqlite.Row) -> Message:
    return Message(
        id=row["id"],
        workspace_id=row["workspace_id"],
        role=row["role"],
        content_markdown=row["content_markdown"],
        linked_agent_run_id=row["linked_agent_run_id"],
        created_at=row["created_at"],
    )


async def create_message(
    db: aiosqlite.Connection, workspace_id: str, data: MessageCreate
) -> Message:
    message_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO message
            (id, workspace_id, role, content_markdown, linked_agent_run_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, workspace_id, data.role, data.content_markdown, data.linked_agent_run_id, now),
    )
    await db.commit()
    return await get_message(db, message_id)  # type: ignore[return-value]


async def get_message(db: aiosqlite.Connection, message_id: str) -> Message | None:
    cursor = await db.execute("SELECT * FROM message WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    return _row_to_message(row) if row else None


async def list_messages(
    db: aiosqlite.Connection,
    workspace_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[Message]:
    cursor = await db.execute(
        "SELECT * FROM message WHERE workspace_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (workspace_id, limit, offset),
    )
    return [_row_to_message(row) for row in await cursor.fetchall()]


async def delete_message(db: aiosqlite.Connection, message_id: str) -> bool:
    cursor = await db.execute("DELETE FROM message WHERE id = ?", (message_id,))
    await db.commit()
    return cursor.rowcount > 0
