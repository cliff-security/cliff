"""Fixtures for repo-knowledge-base tests — in-memory SQLite with migrations."""

from __future__ import annotations

import pytest


@pytest.fixture
async def db():
    """An aiosqlite.Connection backed by an in-memory DB with all migrations run."""
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()
