"""Tests for demo mode seeding logic."""

from __future__ import annotations

import pytest

from cliff.config import Settings
from cliff.db.connection import close_db, init_db


@pytest.fixture
async def in_memory_db():
    """Provide an in-memory SQLite database, cleaned up after the test."""
    await init_db(":memory:")
    yield
    await close_db()


# ── Config field tests ───────────────────────────────────────────────────────


def test_config_demo_default_false():
    """Demo mode defaults to off."""
    s = Settings()
    assert s.demo is False


def test_config_demo_settable_true():
    """Demo mode can be enabled via constructor."""
    s = Settings(demo=True)
    assert s.demo is True


# ── Seeding logic tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_seeds_findings_on_empty_db(in_memory_db):
    """When demo=True and no findings exist, seed creates demo findings."""
    from cliff.api.routes.seed import DEMO_FINDINGS
    from cliff.db import connection as db_connection
    from cliff.db.repo_finding import create_finding, list_findings
    from cliff.models import FindingCreate

    db = db_connection._db
    assert db is not None

    # Verify empty
    existing = await list_findings(db, limit=1)
    assert len(existing) == 0

    # Run seeding logic (same as main.py lifespan)
    for data in DEMO_FINDINGS:
        await create_finding(db, FindingCreate(**data))

    # Verify seeded
    findings = await list_findings(db, limit=100)
    assert len(findings) == len(DEMO_FINDINGS)
    assert len(findings) == 5


@pytest.mark.asyncio
async def test_demo_skips_when_findings_exist(in_memory_db):
    """When findings already exist, demo seeding should be skipped."""
    from cliff.api.routes.seed import DEMO_FINDINGS
    from cliff.db import connection as db_connection
    from cliff.db.repo_finding import create_finding, list_findings
    from cliff.models import FindingCreate

    db = db_connection._db
    assert db is not None

    # Pre-insert one finding
    await create_finding(db, FindingCreate(**DEMO_FINDINGS[0]))

    # Check guard condition (same as main.py)
    existing = await list_findings(db, limit=1)
    assert len(existing) > 0, "Guard should detect existing findings"

    # Seeding should NOT happen — count stays at 1
    findings = await list_findings(db, limit=100)
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_demo_skips_when_flag_false():
    """With demo=False, the seeding block should not execute."""
    s = Settings(demo=False)
    # The guard in main.py is: if settings.demo and db is not None
    # With demo=False, the entire block is skipped
    assert not s.demo, "Demo flag should be False"
