"""Repository functions for the ``ai_integration`` table (IMPL-0011)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.ai.models import AIIntegration, AIProvider, AISource

if TYPE_CHECKING:
    import aiosqlite


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_record(row: aiosqlite.Row) -> AIIntegration:
    metadata_raw = row["metadata_json"]
    metadata = json.loads(metadata_raw) if metadata_raw else None
    return AIIntegration(
        id=row["id"],
        integration_id=row["integration_id"],
        provider=row["provider"],
        source=row["source"],
        metadata=metadata,
        connected_at=row["connected_at"],
        last_validated_at=row["last_validated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    db: aiosqlite.Connection,
    *,
    integration_id: str,
    provider: AIProvider,
    source: AISource,
    metadata: dict | None = None,
) -> AIIntegration:
    """Insert a fresh ``ai_integration`` row. Returns the new record."""
    row_id = str(uuid.uuid4())
    now = _now_iso()
    metadata_json = json.dumps(metadata) if metadata is not None else None
    await db.execute(
        """
        INSERT INTO ai_integration
            (id, integration_id, provider, source, metadata_json,
             connected_at, last_validated_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (row_id, integration_id, provider, source, metadata_json, now, now, now),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM ai_integration WHERE id = ?", (row_id,)
    )
    row = await cursor.fetchone()
    assert row is not None  # just inserted
    return _row_to_record(row)


async def get_active(db: aiosqlite.Connection) -> AIIntegration | None:
    """Return the most recently connected AI integration, or ``None``.

    Single-row-per-provider, but a user can swap providers — return the
    latest. Callers treat the result as authoritative.
    """
    cursor = await db.execute(
        "SELECT * FROM ai_integration ORDER BY connected_at DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    return _row_to_record(row) if row else None


async def get_by_integration_id(
    db: aiosqlite.Connection, integration_id: str
) -> AIIntegration | None:
    cursor = await db.execute(
        "SELECT * FROM ai_integration WHERE integration_id = ?", (integration_id,)
    )
    row = await cursor.fetchone()
    return _row_to_record(row) if row else None


async def get_by_provider(
    db: aiosqlite.Connection, provider: AIProvider
) -> AIIntegration | None:
    cursor = await db.execute(
        "SELECT * FROM ai_integration WHERE provider = ?", (provider,)
    )
    row = await cursor.fetchone()
    return _row_to_record(row) if row else None


async def update_last_validated(
    db: aiosqlite.Connection, integration_id: str
) -> AIIntegration | None:
    now = _now_iso()
    await db.execute(
        """
        UPDATE ai_integration
        SET last_validated_at = ?, updated_at = ?
        WHERE integration_id = ?
        """,
        (now, now, integration_id),
    )
    await db.commit()
    return await get_by_integration_id(db, integration_id)


async def delete(db: aiosqlite.Connection, integration_id: str) -> bool:
    """Delete the ai_integration row. Returns True if it existed."""
    cursor = await db.execute(
        "DELETE FROM ai_integration WHERE integration_id = ?", (integration_id,)
    )
    await db.commit()
    return cursor.rowcount > 0
