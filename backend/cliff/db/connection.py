"""Database connection lifecycle and FastAPI dependency."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiosqlite

from cliff.db.migrations import run_migrations

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


async def init_db(db_path: Path | str) -> aiosqlite.Connection:
    """Open the SQLite database, enable WAL + FK, and run migrations."""
    global _db  # noqa: PLW0603

    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")

    applied = await run_migrations(db)
    logger.info("Database ready at %s (%d new migrations applied)", db_path, applied)

    _db = db
    return db


async def close_db() -> None:
    """Close the database connection."""
    global _db  # noqa: PLW0603
    if _db is not None:
        await _db.close()
        _db = None


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """FastAPI dependency that yields the database connection."""
    if _db is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    yield _db
