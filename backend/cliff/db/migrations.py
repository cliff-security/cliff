"""Run numbered SQL migration scripts against the database."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations(db: aiosqlite.Connection, migrations_dir: Path | None = None) -> int:
    """Apply any unapplied migrations from *migrations_dir* (default: ``migrations/``).

    Returns the number of newly applied migrations.
    """
    migrations_dir = migrations_dir or MIGRATIONS_DIR

    # Bootstrap the tracking table.
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    await db.commit()

    # Discover migration files sorted by numeric prefix.
    sql_files = sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)
    if not sql_files:
        return 0

    # Determine which have already been applied.
    cursor = await db.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}

    count = 0
    for path in sql_files:
        if path.name in applied:
            continue
        logger.info("Applying migration %s", path.name)
        sql = path.read_text()
        await db.executescript(sql)
        await db.execute("INSERT INTO _migrations (name) VALUES (?)", (path.name,))
        await db.commit()
        count += 1

    return count
