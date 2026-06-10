"""Tests for SQL migration 024 (ADR-0051 / IMPL-0024 M1 — triage contract).

Migration 024 does two additive things, both required by the triage step:

  1. Rebuilds the ``finding.exception_reason`` CHECK constraint to add the new
     ``unexploitable`` reason (SQLite cannot ``ALTER`` a CHECK, so the table is
     rebuilt). The rebuild MUST preserve every existing row and must not
     cascade-delete child rows (``workspace`` references ``finding``).
  2. Adds a nullable JSON ``triage`` column to ``sidebar_state`` so the
     ``SidebarState.triage`` section can persist.

Note: IMPL-0024 §3.1 claimed the sidebar ``triage`` section needed no
migration ("per-workspace JSON context"); the live ``sidebar_state`` schema is
columnar (each section is its own JSON column, e.g. ``pull_request`` added by
migration 007), so a column add is in fact required. This deviation is called
out in the PR.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from cliff.db.migrations import run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "cliff" / "db" / "migrations"

_EXISTING_REASONS = ("false_positive", "accepted_risk", "wont_fix", "deferred")


def _copy_migrations_upto(dst: Path, upto: int) -> None:
    """Copy ``NNN_*.sql`` files whose numeric prefix is ``<= upto`` into *dst*."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name.split("_", 1)[0]) <= upto:
            shutil.copy(path, dst / path.name)


async def _insert_finding(
    db: aiosqlite.Connection,
    *,
    finding_id: str,
    status: str = "new",
    exception_reason: str | None = None,
    exception_note: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO finding
            (id, source_type, source_id, title, status,
             exception_reason, exception_note, created_at, updated_at)
        VALUES (?, 'tenable', ?, 'Test finding', ?, ?, ?, ?, ?)
        """,
        (finding_id, finding_id, status, exception_reason, exception_note, now, now),
    )
    await db.commit()


async def _table_columns(db: aiosqlite.Connection, table: str) -> dict[str, tuple[str, int]]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    # row shape: (cid, name, type, notnull, dflt_value, pk)
    return {row[1]: (row[2], row[3]) for row in rows}


@pytest.fixture
async def db_at_023(tmp_path):
    """A FK-enforcing in-memory DB migrated to 023 (pre-triage), with the
    migrations dir staged in *tmp_path* so 024 can be applied incrementally."""
    staged = tmp_path / "migrations"
    _copy_migrations_upto(staged, 23)
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await run_migrations(conn, migrations_dir=staged)
    try:
        yield conn, staged
    finally:
        await conn.close()


async def _apply_024(conn: aiosqlite.Connection, staged: Path) -> int:
    """Stage migration 024 alongside the already-applied ones and run it."""
    src = MIGRATIONS_DIR / "024_triage_contract.sql"
    assert src.exists(), f"Expected migration file at {src}"
    shutil.copy(src, staged / src.name)
    return await run_migrations(conn, migrations_dir=staged)


async def test_023_rejects_unexploitable_before_rebuild(db_at_023) -> None:
    """Guard: the pre-024 CHECK genuinely rejects ``unexploitable`` — so the
    'now accepted' assertion below is meaningful, not vacuous."""
    conn, _ = db_at_023
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_finding(
            conn, finding_id="f-pre", status="exception",
            exception_reason="unexploitable",
        )


async def test_024_applies_and_is_recorded(db_at_023) -> None:
    conn, staged = db_at_023
    applied = await _apply_024(conn, staged)
    assert applied == 1
    cursor = await conn.execute("SELECT name FROM _migrations")
    names = {row[0] for row in await cursor.fetchall()}
    assert "024_triage_contract.sql" in names


async def test_024_preserves_existing_exception_rows(db_at_023) -> None:
    conn, staged = db_at_023
    for reason in _EXISTING_REASONS:
        await _insert_finding(
            conn, finding_id=f"f-{reason}", status="exception",
            exception_reason=reason, exception_note=f"note-{reason}",
        )
    await _insert_finding(conn, finding_id="f-new", status="new")

    await _apply_024(conn, staged)

    for reason in _EXISTING_REASONS:
        cursor = await conn.execute(
            "SELECT status, exception_reason, exception_note FROM finding WHERE id = ?",
            (f"f-{reason}",),
        )
        row = await cursor.fetchone()
        assert tuple(row) == ("exception", reason, f"note-{reason}")
    cursor = await conn.execute(
        "SELECT status, exception_reason FROM finding WHERE id = 'f-new'"
    )
    assert tuple(await cursor.fetchone()) == ("new", None)


async def test_024_does_not_cascade_delete_child_workspaces(db_at_023) -> None:
    """The finding-table rebuild must run with foreign keys disabled, or
    dropping the old ``finding`` table would cascade through the
    ``workspace.finding_id`` reference and wipe child rows."""
    conn, staged = db_at_023
    await _insert_finding(conn, finding_id="f-parent", status="new")
    now = datetime.now(UTC).isoformat()
    await conn.execute(
        "INSERT INTO workspace (id, finding_id, created_at, updated_at)"
        " VALUES ('ws-child', 'f-parent', ?, ?)",
        (now, now),
    )
    await conn.commit()

    await _apply_024(conn, staged)

    cursor = await conn.execute(
        "SELECT finding_id FROM workspace WHERE id = 'ws-child'"
    )
    row = await cursor.fetchone()
    assert row is not None, "child workspace row was cascade-deleted by the rebuild"
    assert row["finding_id"] == "f-parent"
    # FK graph is intact after the rebuild.
    cursor = await conn.execute("PRAGMA foreign_key_check")
    assert await cursor.fetchall() == []


async def test_024_accepts_unexploitable_reason(db_at_023) -> None:
    conn, staged = db_at_023
    await _apply_024(conn, staged)
    await _insert_finding(
        conn, finding_id="f-unexp", status="exception",
        exception_reason="unexploitable", exception_note="air-gapped",
    )
    cursor = await conn.execute(
        "SELECT exception_reason, exception_note FROM finding WHERE id = 'f-unexp'"
    )
    assert tuple(await cursor.fetchone()) == ("unexploitable", "air-gapped")


async def test_024_still_rejects_unknown_reason(db_at_023) -> None:
    conn, staged = db_at_023
    await _apply_024(conn, staged)
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_finding(
            conn, finding_id="f-bad", status="exception", exception_reason="bogus",
        )


async def test_024_adds_sidebar_triage_column(db_at_023) -> None:
    conn, staged = db_at_023
    assert "triage" not in await _table_columns(conn, "sidebar_state")
    await _apply_024(conn, staged)
    cols = await _table_columns(conn, "sidebar_state")
    assert "triage" in cols, "sidebar_state.triage missing after migration 024"
    col_type, notnull = cols["triage"]
    assert col_type.upper().startswith("TEXT")
    assert notnull == 0, "triage must be nullable"
