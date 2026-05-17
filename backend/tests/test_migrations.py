"""Tests for SQL migration 008 (EXEC-0002 contracts freeze).

Verifies the schema additions from IMPL-0002 Milestone A:
  - finding.plain_description column
  - assessment table
  - posture_check table
  - completion table (with share_actions_used JSON column)

Kept separate from test_db.py so the `db` fixture there can continue to target
pre-migration-008 assertions.
"""

from __future__ import annotations

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


async def _columns(db: aiosqlite.Connection, table: str) -> dict[str, str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    # row shape: (cid, name, type, notnull, dflt_value, pk)
    return {row[1]: row[2] for row in rows}


async def test_008_migration_file_exists() -> None:
    target = MIGRATIONS_DIR / "008_from_zero_to_secure.sql"
    assert target.exists(), f"Expected migration file at {target}"


async def test_008_migration_applied(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}
    assert "008_from_zero_to_secure.sql" in applied


async def test_008_schema_matches_expected(db: aiosqlite.Connection) -> None:
    # finding gains plain_description
    finding_cols = await _columns(db, "finding")
    assert "plain_description" in finding_cols
    assert finding_cols["plain_description"].upper().startswith("TEXT")

    # assessment
    assessment_cols = await _columns(db, "assessment")
    for col in (
        "id",
        "repo_url",
        "started_at",
        "completed_at",
        "status",
        "grade",
        "criteria_snapshot",
    ):
        assert col in assessment_cols, f"assessment.{col} missing"

    # posture_check is dropped by migration 011 (ADR-0033). Posture rows now
    # live in the unified ``finding`` table per ADR-0027 — verify the v0.2
    # columns landed correctly there.
    finding_cols_v2 = await _columns(db, "finding")
    for col in (
        "type",
        "grade_impact",
        "category",
        "assessment_id",
        "pr_url",
    ):
        assert col in finding_cols_v2, f"finding.{col} missing post-011"

    # completion — includes share_actions_used (JSON text per SQLite)
    completion_cols = await _columns(db, "completion")
    for col in (
        "id",
        "assessment_id",
        "repo_url",
        "completed_at",
        "criteria_snapshot",
        "share_actions_used",
    ):
        assert col in completion_cols, f"completion.{col} missing"
