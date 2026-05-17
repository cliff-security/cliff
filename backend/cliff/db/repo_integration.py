"""Repository functions for the IntegrationConfig entity."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import IntegrationConfig, IntegrationConfigCreate, IntegrationConfigUpdate

if TYPE_CHECKING:
    import aiosqlite


def _row_to_integration(row: aiosqlite.Row) -> IntegrationConfig:
    return IntegrationConfig(
        id=row["id"],
        adapter_type=row["adapter_type"],
        provider_name=row["provider_name"],
        enabled=bool(row["enabled"]),
        config=json.loads(row["config"]) if row["config"] else None,
        last_test_result=json.loads(row["last_test_result"]) if row["last_test_result"] else None,
        action_tier=row["action_tier"],
        updated_at=row["updated_at"],
    )


async def create_integration(
    db: aiosqlite.Connection,
    data: IntegrationConfigCreate,
    *,
    override_id: str | None = None,
) -> IntegrationConfig:
    integration_id = override_id or str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO integration_config
            (id, adapter_type, provider_name, enabled, config, action_tier, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            integration_id,
            data.adapter_type,
            data.provider_name,
            int(data.enabled),
            json.dumps(data.config) if data.config is not None else None,
            data.action_tier,
            now,
        ),
    )
    await db.commit()
    return (await get_integration(db, integration_id))  # type: ignore[return-value]


async def get_integration(
    db: aiosqlite.Connection, integration_id: str
) -> IntegrationConfig | None:
    cursor = await db.execute(
        "SELECT * FROM integration_config WHERE id = ?", (integration_id,)
    )
    row = await cursor.fetchone()
    return _row_to_integration(row) if row else None


async def list_integrations(db: aiosqlite.Connection) -> list[IntegrationConfig]:
    cursor = await db.execute(
        "SELECT * FROM integration_config ORDER BY updated_at DESC"
    )
    return [_row_to_integration(row) for row in await cursor.fetchall()]


async def update_integration(
    db: aiosqlite.Connection, integration_id: str, data: IntegrationConfigUpdate
) -> IntegrationConfig | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_integration(db, integration_id)

    if "config" in fields and fields["config"] is not None:
        fields["config"] = json.dumps(fields["config"])
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])

    fields["updated_at"] = datetime.now(UTC).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), integration_id]

    await db.execute(
        f"UPDATE integration_config SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    await db.commit()
    return await get_integration(db, integration_id)


async def delete_integration(db: aiosqlite.Connection, integration_id: str) -> bool:
    cursor = await db.execute(
        "DELETE FROM integration_config WHERE id = ?", (integration_id,)
    )
    await db.commit()
    return cursor.rowcount > 0
