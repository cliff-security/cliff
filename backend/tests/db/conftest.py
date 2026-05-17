"""Shared fixtures for DAO tests — in-memory SQLite, schema applied."""

from __future__ import annotations

import pytest


@pytest.fixture
async def db():
    """Yield an aiosqlite.Connection backed by an in-memory DB with all migrations run."""
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()
