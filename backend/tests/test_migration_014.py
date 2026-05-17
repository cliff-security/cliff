"""Tests for SQL migration 014 (IMPL-0009 — assessment scope columns).

Verifies that the assessment table gains four nullable scope-and-counter columns
that the new dashboard surfaces:

  - ``commit_sha`` TEXT
  - ``branch`` TEXT
  - ``scanned_files`` INTEGER
  - ``scanned_deps`` INTEGER

NULL must remain valid for all four (older assessments and in-flight rows that
haven't captured the values yet).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cliff.db.connection import close_db, init_db

if TYPE_CHECKING:
    import aiosqlite

MIGRATIONS_DIR = Path(__file__).parent.parent / "cliff" / "db" / "migrations"


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def _columns(db: aiosqlite.Connection, table: str) -> dict[str, tuple[str, int]]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    # row shape: (cid, name, type, notnull, dflt_value, pk)
    return {row[1]: (row[2], row[3]) for row in rows}


async def _insert_assessment(
    db: aiosqlite.Connection,
    *,
    assessment_id: str,
    commit_sha: str | None = None,
    branch: str | None = None,
    scanned_files: int | None = None,
    scanned_deps: int | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO assessment
            (id, repo_url, started_at, completed_at, status,
             commit_sha, branch, scanned_files, scanned_deps)
        VALUES (?, 'https://github.com/x/y', ?, NULL, 'pending', ?, ?, ?, ?)
        """,
        (assessment_id, now, commit_sha, branch, scanned_files, scanned_deps),
    )
    await db.commit()


async def test_014_migration_file_exists() -> None:
    target = MIGRATIONS_DIR / "014_assessment_scope.sql"
    assert target.exists(), f"Expected migration file at {target}"


async def test_014_migration_applied(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}
    assert "014_assessment_scope.sql" in applied


async def test_014_adds_four_scope_columns(db: aiosqlite.Connection) -> None:
    cols = await _columns(db, "assessment")

    assert "commit_sha" in cols, "assessment.commit_sha missing after migration 014"
    cs_type, cs_notnull = cols["commit_sha"]
    assert cs_type.upper().startswith("TEXT")
    assert cs_notnull == 0, "commit_sha must be nullable"

    assert "branch" in cols, "assessment.branch missing after migration 014"
    b_type, b_notnull = cols["branch"]
    assert b_type.upper().startswith("TEXT")
    assert b_notnull == 0, "branch must be nullable"

    assert "scanned_files" in cols, "assessment.scanned_files missing after migration 014"
    sf_type, sf_notnull = cols["scanned_files"]
    assert sf_type.upper().startswith("INT")
    assert sf_notnull == 0, "scanned_files must be nullable"

    assert "scanned_deps" in cols, "assessment.scanned_deps missing after migration 014"
    sd_type, sd_notnull = cols["scanned_deps"]
    assert sd_type.upper().startswith("INT")
    assert sd_notnull == 0, "scanned_deps must be nullable"


async def test_014_accepts_null_scope_fields(db: aiosqlite.Connection) -> None:
    await _insert_assessment(db, assessment_id="a-null")
    cursor = await db.execute(
        "SELECT commit_sha, branch, scanned_files, scanned_deps "
        "FROM assessment WHERE id = ?",
        ("a-null",),
    )
    row = await cursor.fetchone()
    assert tuple(row) == (None, None, None, None)


async def test_014_roundtrips_scope_fields(db: aiosqlite.Connection) -> None:
    await _insert_assessment(
        db,
        assessment_id="a-full",
        commit_sha="a3f81c2",
        branch="main",
        scanned_files=4128,
        scanned_deps=312,
    )
    cursor = await db.execute(
        "SELECT commit_sha, branch, scanned_files, scanned_deps "
        "FROM assessment WHERE id = ?",
        ("a-full",),
    )
    row = await cursor.fetchone()
    assert tuple(row) == ("a3f81c2", "main", 4128, 312)
