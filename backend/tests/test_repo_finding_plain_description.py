"""Ensure ``plain_description`` round-trips through the finding DAO (IMPL-0002 C2)."""

from __future__ import annotations

import pytest

from cliff.models import FindingCreate, FindingUpdate


@pytest.fixture
async def db():
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()


async def test_create_finding_persists_plain_description(db):
    from cliff.db.repo_finding import create_finding, get_finding

    created = await create_finding(
        db,
        FindingCreate(
            source_type="tenable",
            source_id="vuln-001",
            title="CVE-2024-1234 in libfoo",
            plain_description="A remote attacker can crash the app. Upgrade libfoo to 1.2.3.",
        ),
    )
    assert created.plain_description == (
        "A remote attacker can crash the app. Upgrade libfoo to 1.2.3."
    )

    fetched = await get_finding(db, created.id)
    assert fetched is not None
    assert fetched.plain_description == created.plain_description


async def test_create_finding_without_plain_description_is_null(db):
    from cliff.db.repo_finding import create_finding

    created = await create_finding(
        db,
        FindingCreate(source_type="tenable", source_id="vuln-002", title="Older finding"),
    )
    assert created.plain_description is None


async def test_update_finding_sets_plain_description(db):
    from cliff.db.repo_finding import create_finding, update_finding

    created = await create_finding(
        db,
        FindingCreate(source_type="tenable", source_id="vuln-003", title="t"),
    )
    updated = await update_finding(
        db, created.id, FindingUpdate(plain_description="Readable text.")
    )
    assert updated is not None
    assert updated.plain_description == "Readable text."
