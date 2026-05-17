"""Tests for database initialization and migrations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cliff.db.connection import close_db, init_db
from cliff.db.migrations import run_migrations

if TYPE_CHECKING:
    import aiosqlite

MIGRATIONS_DIR = Path(__file__).parent.parent / "cliff" / "db" / "migrations"


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def test_init_db_creates_tables(db: aiosqlite.Connection):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in await cursor.fetchall()}
    expected = {
        "finding",
        "workspace",
        "message",
        "agent_run",
        "sidebar_state",
        "ticket_link",
        "validation_result",
        "app_setting",
        "integration_config",
        "credential",
        "audit_log",
        "_migrations",
    }
    assert expected.issubset(tables)


async def test_wal_mode_enabled(db: aiosqlite.Connection):
    cursor = await db.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    # In-memory databases may report "memory" instead of "wal".
    assert row[0] in ("wal", "memory")


async def test_foreign_keys_enabled(db: aiosqlite.Connection):
    cursor = await db.execute("PRAGMA foreign_keys")
    row = await cursor.fetchone()
    assert row[0] == 1


async def test_migrations_idempotent(db: aiosqlite.Connection):
    # Running migrations a second time should apply 0 new migrations.
    count = await run_migrations(db, MIGRATIONS_DIR)
    assert count == 0


async def test_migrations_tracked(db: aiosqlite.Connection):
    cursor = await db.execute("SELECT name FROM _migrations")
    rows = await cursor.fetchall()
    names = [row[0] for row in rows]
    assert "001_initial_schema.sql" in names
