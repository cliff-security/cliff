"""Repository functions for the credential table (encrypted secret storage)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


async def create_credential(
    db: aiosqlite.Connection,
    integration_id: str,
    key_name: str,
    encrypted_value: bytes,
    iv: bytes,
) -> str:
    """Insert a new credential row. Returns the credential ID."""
    credential_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO credential (id, integration_id, key_name, encrypted_value, iv, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (credential_id, integration_id, key_name, encrypted_value, iv, now),
    )
    await db.commit()
    return credential_id


async def get_credential(
    db: aiosqlite.Connection, integration_id: str, key_name: str
) -> dict | None:
    """Fetch a single credential row by (integration_id, key_name)."""
    cursor = await db.execute(
        "SELECT * FROM credential WHERE integration_id = ? AND key_name = ?",
        (integration_id, key_name),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "integration_id": row["integration_id"],
        "key_name": row["key_name"],
        "encrypted_value": row["encrypted_value"],
        "iv": row["iv"],
        "created_at": row["created_at"],
        "rotated_at": row["rotated_at"],
    }


async def list_credential_keys(
    db: aiosqlite.Connection, integration_id: str
) -> list[dict]:
    """List credential metadata (no encrypted values) for an integration."""
    cursor = await db.execute(
        "SELECT key_name, created_at, rotated_at FROM credential WHERE integration_id = ?",
        (integration_id,),
    )
    return [
        {
            "key_name": row["key_name"],
            "created_at": row["created_at"],
            "rotated_at": row["rotated_at"],
        }
        for row in await cursor.fetchall()
    ]


async def update_credential(
    db: aiosqlite.Connection,
    integration_id: str,
    key_name: str,
    encrypted_value: bytes,
    iv: bytes,
) -> bool:
    """Update encrypted value and IV for an existing credential. Sets rotated_at."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        """
        UPDATE credential
        SET encrypted_value = ?, iv = ?, rotated_at = ?
        WHERE integration_id = ? AND key_name = ?
        """,
        (encrypted_value, iv, now, integration_id, key_name),
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_credential(
    db: aiosqlite.Connection, integration_id: str, key_name: str
) -> bool:
    """Delete a single credential."""
    cursor = await db.execute(
        "DELETE FROM credential WHERE integration_id = ? AND key_name = ?",
        (integration_id, key_name),
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_credentials_for_integration(
    db: aiosqlite.Connection, integration_id: str
) -> int:
    """Delete all credentials for an integration. Returns count deleted."""
    cursor = await db.execute(
        "DELETE FROM credential WHERE integration_id = ?",
        (integration_id,),
    )
    await db.commit()
    return cursor.rowcount
