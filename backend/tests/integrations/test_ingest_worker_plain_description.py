"""Ingest worker preserves ``plain_description`` emitted by the normalizer (IMPL-0002 C2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cliff.models import FindingCreate


@pytest.fixture
async def db():
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()


async def test_process_job_persists_plain_description(db):
    from cliff.db.repo_finding import list_findings
    from cliff.db.repo_ingest_job import create_ingest_job
    from cliff.integrations.ingest_worker import _process_job

    # Create a job with one raw item.
    job = await create_ingest_job(
        db, source="tenable", raw_data=[{"id": "v1", "title": "t"}], chunk_size=1
    )

    # Mock the normalizer to emit a FindingCreate with plain_description set.
    fc = FindingCreate(
        source_type="tenable",
        source_id="v1",
        title="CVE-2024-0001 in libfoo",
        plain_description="Upgrade libfoo to 1.2.3. This blocks a crash bug.",
    )
    mocked = AsyncMock(return_value=([fc], []))
    with patch("cliff.integrations.ingest_worker.normalize_findings", mocked):
        await _process_job(
            db,
            job.job_id,
            env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "k"}),
            model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
        )

    findings = await list_findings(db)
    assert len(findings) == 1
    assert findings[0].plain_description == (
        "Upgrade libfoo to 1.2.3. This blocks a crash bug."
    )
