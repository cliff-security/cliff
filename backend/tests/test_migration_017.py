"""Tests for SQL migration 017 (IMPL-0011 — ai_integration table).

Verifies the new table for tiered AI provider onboarding (ADR-0036):

  - PK ``id`` TEXT
  - ``integration_id`` TEXT NOT NULL UNIQUE REFERENCES integration_config(id)
  - ``provider`` TEXT NOT NULL with CHECK constraint
  - ``source`` TEXT NOT NULL with CHECK constraint
  - ``metadata_json`` TEXT nullable
  - timestamps as ISO 8601 TEXT
  - unique index on ``provider``

The table never stores key material — secrets live in the ``credential``
vault, keyed by ``integration_id`` and ``key_name = 'api_key'``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from cliff.db import repo_integration
from cliff.db.connection import close_db, init_db
from cliff.models import IntegrationConfigCreate

MIGRATIONS_DIR = Path(__file__).parent.parent / "cliff" / "db" / "migrations"


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def _create_integration_row(
    db: aiosqlite.Connection, *, provider_name: str = "openrouter"
) -> str:
    integration = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="ai_provider",
            provider_name=provider_name,
            enabled=True,
            config=None,
            action_tier=0,
        ),
    )
    return integration.id


async def _insert_ai_integration(
    db: aiosqlite.Connection,
    *,
    integration_id: str,
    provider: str = "openrouter",
    source: str = "byok",
    metadata_json: str | None = None,
) -> str:
    import uuid

    row_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
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
    return row_id


async def test_017_migration_file_exists() -> None:
    target = MIGRATIONS_DIR / "017_ai_integration.sql"
    assert target.exists(), f"Expected migration file at {target}"


async def test_017_migration_applied(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}
    assert "017_ai_integration.sql" in applied


async def test_017_creates_ai_integration_table(db: aiosqlite.Connection) -> None:
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_integration'"
    )
    row = await cursor.fetchone()
    assert row is not None, "ai_integration table not created"


async def test_017_columns_present(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(ai_integration)")
    cols = {row[1]: row[2] for row in await cursor.fetchall()}
    assert "id" in cols
    assert "integration_id" in cols
    assert "provider" in cols
    assert "source" in cols
    assert "metadata_json" in cols
    assert "connected_at" in cols
    assert "last_validated_at" in cols
    assert "created_at" in cols
    assert "updated_at" in cols


async def test_017_round_trip_insert_and_read(db: aiosqlite.Connection) -> None:
    integration_id = await _create_integration_row(db)
    await _insert_ai_integration(
        db,
        integration_id=integration_id,
        provider="openrouter",
        source="openrouter-oauth",
        metadata_json='{"user_email":"a@b.co"}',
    )
    cursor = await db.execute(
        "SELECT provider, source, metadata_json FROM ai_integration WHERE integration_id = ?",
        (integration_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert tuple(row) == ("openrouter", "openrouter-oauth", '{"user_email":"a@b.co"}')


async def test_017_rejects_unknown_provider(db: aiosqlite.Connection) -> None:
    integration_id = await _create_integration_row(db)
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_ai_integration(
            db, integration_id=integration_id, provider="bogus"
        )


async def test_017_rejects_unknown_source(db: aiosqlite.Connection) -> None:
    integration_id = await _create_integration_row(db)
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_ai_integration(
            db, integration_id=integration_id, source="manual"
        )


async def test_017_unique_provider_constraint(db: aiosqlite.Connection) -> None:
    integration_a = await _create_integration_row(db, provider_name="openrouter")
    integration_b = await _create_integration_row(db, provider_name="openrouter-2")

    await _insert_ai_integration(
        db, integration_id=integration_a, provider="openrouter"
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_ai_integration(
            db, integration_id=integration_b, provider="openrouter"
        )


async def test_017_integration_id_is_unique(db: aiosqlite.Connection) -> None:
    integration_id = await _create_integration_row(db)
    await _insert_ai_integration(
        db, integration_id=integration_id, provider="openrouter"
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_ai_integration(
            db, integration_id=integration_id, provider="anthropic"
        )


async def test_017_cascade_on_integration_delete(db: aiosqlite.Connection) -> None:
    integration_id = await _create_integration_row(db)
    await _insert_ai_integration(db, integration_id=integration_id)

    deleted = await repo_integration.delete_integration(db, integration_id)
    assert deleted is True

    cursor = await db.execute(
        "SELECT id FROM ai_integration WHERE integration_id = ?",
        (integration_id,),
    )
    assert await cursor.fetchone() is None
