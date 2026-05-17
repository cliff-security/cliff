"""Tests for SQL migration 020 (ADR-0037 — add google/ollama providers).

The migration rebuilds ``ai_integration`` to widen its provider CHECK
constraint. The architect's health-check flagged H2: under the original
``PRAGMA foreign_keys = OFF`` (a no-op inside ``executescript``'s
implicit transaction) the ``DROP TABLE`` would have tripped the
``integration_config -> ai_integration`` FK cascade on any installed
instance that already held an AI integration row, silently losing the
user's connection on upgrade.

This test exercises the upgrade path on a *populated* database: it
applies migrations 001-019, inserts a sample integration_config +
ai_integration pair, applies 020, then asserts every column round-trips
and the FK cascade still works post-rebuild.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from opensec.db.migrations import run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "opensec" / "db" / "migrations"


@pytest.fixture
async def populated_db():
    """Apply migrations 001-019 to an in-memory DB, returning the connection.

    We deliberately do NOT use ``init_db`` because that would apply 020
    too — we need to insert a row under the pre-020 schema and then run
    020 against it.
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")

    pre_020_dir = Path(__file__).parent / "_migrations_pre_020"
    pre_020_dir.mkdir(exist_ok=True)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name >= "020":
            continue
        target = pre_020_dir / path.name
        target.write_text(path.read_text())
    try:
        await run_migrations(conn, pre_020_dir)
        yield conn
    finally:
        for path in pre_020_dir.glob("*.sql"):
            path.unlink()
        pre_020_dir.rmdir()
        await conn.close()


async def _insert_integration_with_ai_row(
    db: aiosqlite.Connection,
    *,
    provider: str = "anthropic",
    source: str = "byok",
) -> tuple[str, str]:
    """Insert a parent integration_config + child ai_integration row.

    Returns ``(integration_id, ai_integration_id)`` so the test can later
    verify both survive the migration rebuild.
    """
    integration_id = str(uuid.uuid4())
    ai_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO integration_config
            (id, adapter_type, provider_name, enabled, config, updated_at)
        VALUES (?, 'ai_provider', ?, 1, NULL, ?)
        """,
        (integration_id, provider, now),
    )
    await db.execute(
        """
        INSERT INTO ai_integration
            (id, integration_id, provider, source, metadata_json,
             connected_at, last_validated_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            ai_id,
            integration_id,
            provider,
            source,
            json.dumps({"source_path": "/home/u/.env"}),
            now,
            now,
            now,
        ),
    )
    await db.commit()
    return integration_id, ai_id


async def test_020_preserves_existing_ai_integration_row(populated_db):
    """The table rebuild must not lose a pre-existing AI integration row."""
    integration_id, ai_id = await _insert_integration_with_ai_row(
        populated_db, provider="anthropic", source="byok"
    )

    # Apply just migration 020.
    sql_020 = (MIGRATIONS_DIR / "020_ai_integration_google_ollama.sql").read_text()
    await populated_db.executescript(sql_020)
    await populated_db.commit()

    cursor = await populated_db.execute(
        """
        SELECT id, integration_id, provider, source, metadata_json,
               connected_at, created_at, updated_at
        FROM ai_integration
        WHERE id = ?
        """,
        (ai_id,),
    )
    row = await cursor.fetchone()
    assert row is not None, "ai_integration row was lost during migration 020"
    assert row["id"] == ai_id
    assert row["integration_id"] == integration_id
    assert row["provider"] == "anthropic"
    assert row["source"] == "byok"
    assert json.loads(row["metadata_json"]) == {"source_path": "/home/u/.env"}


async def test_020_widens_provider_check_constraint(populated_db):
    """After 020, google + ollama must be insertable; bogus still rejected."""
    sql_020 = (MIGRATIONS_DIR / "020_ai_integration_google_ollama.sql").read_text()
    await populated_db.executescript(sql_020)
    await populated_db.commit()

    for provider in ("google", "ollama"):
        integration_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await populated_db.execute(
            """
            INSERT INTO integration_config
                (id, adapter_type, provider_name, enabled, config, updated_at)
            VALUES (?, 'ai_provider', ?, 1, NULL, ?)
            """,
            (integration_id, provider, now),
        )
        await populated_db.execute(
            """
            INSERT INTO ai_integration
                (id, integration_id, provider, source, metadata_json,
                 connected_at, last_validated_at, created_at, updated_at)
            VALUES (?, ?, ?, 'byok', NULL, ?, NULL, ?, ?)
            """,
            (str(uuid.uuid4()), integration_id, provider, now, now, now),
        )
    await populated_db.commit()

    # Bogus provider still rejected.
    integration_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await populated_db.execute(
        """
        INSERT INTO integration_config
            (id, adapter_type, provider_name, enabled, config, updated_at)
        VALUES (?, 'ai_provider', 'bogus', 1, NULL, ?)
        """,
        (integration_id, now),
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await populated_db.execute(
            """
            INSERT INTO ai_integration
                (id, integration_id, provider, source, metadata_json,
                 connected_at, last_validated_at, created_at, updated_at)
            VALUES (?, ?, 'bogus', 'byok', NULL, ?, NULL, ?, ?)
            """,
            (str(uuid.uuid4()), integration_id, now, now, now),
        )


async def test_020_preserves_fk_cascade_post_rebuild(populated_db):
    """Deleting integration_config still cascades to ai_integration."""
    integration_id, ai_id = await _insert_integration_with_ai_row(populated_db)

    sql_020 = (MIGRATIONS_DIR / "020_ai_integration_google_ollama.sql").read_text()
    await populated_db.executescript(sql_020)
    await populated_db.commit()

    await populated_db.execute(
        "DELETE FROM integration_config WHERE id = ?", (integration_id,)
    )
    await populated_db.commit()

    cursor = await populated_db.execute(
        "SELECT id FROM ai_integration WHERE id = ?", (ai_id,)
    )
    assert await cursor.fetchone() is None, (
        "FK cascade broken: ai_integration row survived integration_config delete"
    )


async def test_020_preserves_unique_index_on_provider(populated_db):
    """The unique index on provider must be re-created after rebuild."""
    sql_020 = (MIGRATIONS_DIR / "020_ai_integration_google_ollama.sql").read_text()
    await populated_db.executescript(sql_020)
    await populated_db.commit()

    cursor = await populated_db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='ai_integration' "
        "AND name='idx_ai_integration_provider'"
    )
    assert await cursor.fetchone() is not None, (
        "unique index idx_ai_integration_provider is missing after rebuild"
    )

    # And the uniqueness is enforced.
    integration_a = str(uuid.uuid4())
    integration_b = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    for iid in (integration_a, integration_b):
        await populated_db.execute(
            """
            INSERT INTO integration_config
                (id, adapter_type, provider_name, enabled, config, updated_at)
            VALUES (?, 'ai_provider', 'anthropic', 1, NULL, ?)
            """,
            (iid, now),
        )
    await populated_db.execute(
        """
        INSERT INTO ai_integration
            (id, integration_id, provider, source, metadata_json,
             connected_at, last_validated_at, created_at, updated_at)
        VALUES (?, ?, 'anthropic', 'byok', NULL, ?, NULL, ?, ?)
        """,
        (str(uuid.uuid4()), integration_a, now, now, now),
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await populated_db.execute(
            """
            INSERT INTO ai_integration
                (id, integration_id, provider, source, metadata_json,
                 connected_at, last_validated_at, created_at, updated_at)
            VALUES (?, ?, 'anthropic', 'byok', NULL, ?, NULL, ?, ?)
            """,
            (str(uuid.uuid4()), integration_b, now, now, now),
        )
