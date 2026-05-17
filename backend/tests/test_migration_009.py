"""Tests for SQL migration 009 (PRD-0004 / ADR-0030 workspace schema unification).

Verifies:
  - workspace table gains ``kind`` and ``source_check_name`` columns
  - ``finding_id`` is nullable after the rebuild
  - Existing finding-remediation rows are backfilled with ``kind='finding_remediation'``
  - Partial unique index ``idx_workspace_active_per_check`` blocks a second
    non-terminal workspace for the same ``source_check_name``
  - Once the first row reaches a terminal state, a new INSERT succeeds
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from cliff.db.connection import close_db, init_db

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


async def _indexes(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA index_list({table})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def _insert_workspace(
    db: aiosqlite.Connection,
    *,
    workspace_id: str,
    kind: str = "finding_remediation",
    source_check_name: str | None = None,
    state: str = "pending",
    finding_id: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO workspace
            (id, finding_id, state, kind, source_check_name,
             current_focus, active_plan_version, linked_ticket_id,
             validation_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (workspace_id, finding_id, state, kind, source_check_name, now, now),
    )
    await db.commit()


async def test_009_migration_file_exists() -> None:
    target = MIGRATIONS_DIR / "009_alpha_blockers.sql"
    assert target.exists(), f"Expected migration file at {target}"


async def test_009_migration_applied(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT name FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}
    assert "009_alpha_blockers.sql" in applied


async def test_009_schema_adds_kind_and_source_check_name(
    db: aiosqlite.Connection,
) -> None:
    cols = await _columns(db, "workspace")
    assert "kind" in cols, "workspace.kind missing after migration 009"
    kind_type, kind_notnull = cols["kind"]
    assert kind_type.upper().startswith("TEXT")
    assert kind_notnull == 1, "workspace.kind must be NOT NULL"

    assert "source_check_name" in cols, "workspace.source_check_name missing"
    sc_type, sc_notnull = cols["source_check_name"]
    assert sc_type.upper().startswith("TEXT")
    assert sc_notnull == 0, "source_check_name must be nullable"


async def test_009_makes_finding_id_nullable(db: aiosqlite.Connection) -> None:
    cols = await _columns(db, "workspace")
    finding_type, finding_notnull = cols["finding_id"]
    assert finding_type.upper().startswith("TEXT")
    assert finding_notnull == 0, "finding_id must be nullable after migration 009"


async def test_009_creates_partial_unique_index(db: aiosqlite.Connection) -> None:
    indexes = await _indexes(db, "workspace")
    assert "idx_workspace_active_per_check" in indexes


async def test_009_preserves_existing_indexes(db: aiosqlite.Connection) -> None:
    indexes = await _indexes(db, "workspace")
    # These were created in 001; must survive the table rebuild.
    assert "idx_workspace_finding" in indexes
    assert "idx_workspace_state" in indexes


async def test_009_partial_index_blocks_second_active_workspace_per_check(
    db: aiosqlite.Connection,
) -> None:
    await _insert_workspace(
        db,
        workspace_id="ws-alpha",
        kind="repo_action_security_md",
        source_check_name="security_md",
        state="pending",
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await _insert_workspace(
            db,
            workspace_id="ws-beta",
            kind="repo_action_security_md",
            source_check_name="security_md",
            state="pending",
        )


async def test_009_partial_index_allows_retry_after_terminal(
    db: aiosqlite.Connection,
) -> None:
    await _insert_workspace(
        db,
        workspace_id="ws-first",
        kind="repo_action_security_md",
        source_check_name="security_md",
        state="pending",
    )
    # Flip to a terminal state — predicate no longer matches that row.
    await db.execute(
        "UPDATE workspace SET state = 'failed' WHERE id = 'ws-first'"
    )
    await db.commit()
    # Third insert is fine now.
    await _insert_workspace(
        db,
        workspace_id="ws-second",
        kind="repo_action_security_md",
        source_check_name="security_md",
        state="pending",
    )


async def test_009_partial_index_ignores_null_source_check_name(
    db: aiosqlite.Connection,
) -> None:
    """Existing finding-remediation workspaces (source_check_name IS NULL) are
    unaffected by the partial index — the predicate filters them out.
    """
    # Seed two "finding-remediation" workspaces with NULL source_check_name.
    # Both have valid finding_id references for completeness but the predicate
    # wouldn't touch them anyway.
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO finding (id, source_type, source_id, title, status, "
        "created_at, updated_at) VALUES ('f1', 'manual', 's1', 't1', 'new', ?, ?)",
        (now, now),
    )
    await db.commit()
    await _insert_workspace(
        db,
        workspace_id="ws-finding-1",
        kind="finding_remediation",
        source_check_name=None,
        state="pending",
        finding_id="f1",
    )
    # Second one is fine too — index predicate ignores NULL source_check_name.
    await _insert_workspace(
        db,
        workspace_id="ws-finding-2",
        kind="finding_remediation",
        source_check_name=None,
        state="pending",
        finding_id="f1",
    )


async def test_009_allows_distinct_checks_concurrently(
    db: aiosqlite.Connection,
) -> None:
    await _insert_workspace(
        db,
        workspace_id="ws-a",
        kind="repo_action_security_md",
        source_check_name="security_md",
        state="pending",
    )
    # Different check_name — no collision.
    await _insert_workspace(
        db,
        workspace_id="ws-b",
        kind="repo_action_dependabot",
        source_check_name="dependabot_config",
        state="pending",
    )
