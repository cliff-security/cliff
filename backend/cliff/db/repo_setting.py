"""Repository functions for the AppSetting entity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import AppSetting

if TYPE_CHECKING:
    import aiosqlite


def _row_to_setting(row: aiosqlite.Row) -> AppSetting:
    return AppSetting(
        key=row["key"],
        value=json.loads(row["value"]) if row["value"] else None,
        updated_at=row["updated_at"],
    )


async def get_setting(db: aiosqlite.Connection, key: str) -> AppSetting | None:
    cursor = await db.execute("SELECT * FROM app_setting WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return _row_to_setting(row) if row else None


async def upsert_setting(
    db: aiosqlite.Connection, key: str, value: dict | None
) -> AppSetting:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO app_setting (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value) if value is not None else None, now),
    )
    await db.commit()
    return (await get_setting(db, key))  # type: ignore[return-value]


async def list_settings(
    db: aiosqlite.Connection, *, prefix: str | None = None
) -> list[AppSetting]:
    if prefix:
        cursor = await db.execute(
            "SELECT * FROM app_setting WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        )
    else:
        cursor = await db.execute("SELECT * FROM app_setting ORDER BY key")
    return [_row_to_setting(row) for row in await cursor.fetchall()]


async def delete_setting(db: aiosqlite.Connection, key: str) -> bool:
    cursor = await db.execute("DELETE FROM app_setting WHERE key = ?", (key,))
    await db.commit()
    return cursor.rowcount > 0
