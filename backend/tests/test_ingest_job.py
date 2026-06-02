"""Tests for async chunked finding ingestion (ADR-0023).

Covers: repo_ingest_job CRUD, estimate_tokens, ingest_worker logic, and API routes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from cliff.integrations.ingest_worker import estimate_tokens

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_single_chunk(self):
        raw = [{"id": "1", "title": "test"}]
        tokens = estimate_tokens(raw, chunk_size=10)
        assert tokens > 0
        # 1 chunk -> 800 fixed + raw_chars / 3.5
        raw_chars = len(json.dumps(raw, separators=(",", ":")))
        expected = int(raw_chars / 3.5) + 800
        assert tokens == expected

    def test_multiple_chunks(self):
        raw = [{"id": str(i)} for i in range(25)]
        tokens = estimate_tokens(raw, chunk_size=10)
        # 3 chunks -> 3 * 800 = 2400 fixed overhead
        assert tokens > 2400

    def test_empty_data(self):
        tokens = estimate_tokens([], chunk_size=10)
        assert tokens == 0


# ---------------------------------------------------------------------------
# DB repo functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_ingest_job():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    raw = [{"id": "1", "title": "test"}]
    job = await create_ingest_job(
        db, source="wiz", raw_data=raw, chunk_size=10, estimated_tokens=500
    )
    assert job.status == "pending"
    assert job.total_items == 1
    assert job.total_chunks == 1
    assert job.chunk_size == 10
    assert job.estimated_tokens == 500
    assert job.poll_url == f"/api/findings/ingest/{job.job_id}"

    progress = await get_ingest_job(db, job.job_id)
    assert progress is not None
    assert progress.status == "pending"
    assert progress.completed_chunks == 0
    assert progress.errors == []
    await close_db()


@pytest.mark.asyncio
async def test_set_job_status():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import (
        create_ingest_job,
        get_ingest_job,
        set_job_status,
    )

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    job = await create_ingest_job(db, source="snyk", raw_data=[{"a": 1}])
    await set_job_status(db, job.job_id, "processing")
    progress = await get_ingest_job(db, job.job_id)
    assert progress.status == "processing"
    await close_db()


@pytest.mark.asyncio
async def test_increment_completed_chunk():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import (
        create_ingest_job,
        get_ingest_job,
        increment_completed_chunk,
    )

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    job = await create_ingest_job(
        db, source="trivy", raw_data=[{"a": 1}] * 5, chunk_size=2
    )
    await increment_completed_chunk(db, job.job_id, 2)
    progress = await get_ingest_job(db, job.job_id)
    assert progress.completed_chunks == 1
    assert progress.findings_created == 2
    await close_db()


@pytest.mark.asyncio
async def test_increment_failed_chunk():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import (
        create_ingest_job,
        get_ingest_job,
        increment_failed_chunk,
    )

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    job = await create_ingest_job(db, source="wiz", raw_data=[{"a": 1}])
    await increment_failed_chunk(db, job.job_id, "LLM timeout")
    progress = await get_ingest_job(db, job.job_id)
    assert progress.failed_chunks == 1
    assert progress.errors == ["LLM timeout"]
    await close_db()


@pytest.mark.asyncio
async def test_get_next_pending_job_id():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import (
        create_ingest_job,
        get_next_pending_job_id,
        set_job_status,
    )

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    # No jobs yet
    assert await get_next_pending_job_id(db) is None

    job1 = await create_ingest_job(db, source="a", raw_data=[{"x": 1}])
    job2 = await create_ingest_job(db, source="b", raw_data=[{"y": 2}])

    # Returns oldest pending
    next_id = await get_next_pending_job_id(db)
    assert next_id == job1.job_id

    # Mark first as completed — should return second
    await set_job_status(db, job1.job_id, "completed")
    next_id = await get_next_pending_job_id(db)
    assert next_id == job2.job_id
    await close_db()


@pytest.mark.asyncio
async def test_get_ingest_job_raw_data():
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job_raw_data

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    raw = [{"id": "1"}, {"id": "2"}]
    job = await create_ingest_job(db, source="wiz", raw_data=raw, chunk_size=5)
    result = await get_ingest_job_raw_data(db, job.job_id)
    assert result is not None
    source, data, chunk_size, model = result
    assert source == "wiz"
    assert data == raw
    assert chunk_size == 5
    assert model is None
    await close_db()


# ---------------------------------------------------------------------------
# Ingest worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_job_success():
    """Worker processes a job with multiple chunks successfully."""
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    # Use 8 items to exceed _SMALL_IMPORT_THRESHOLD (5), so chunk_size=3 is kept
    raw = [{"id": str(i), "title": f"Finding {i}"} for i in range(8)]
    job = await create_ingest_job(db, source="wiz", raw_data=raw, chunk_size=3)

    # Mock normalize_findings to return valid FindingCreate objects
    from cliff.models import FindingCreate

    async def _mock_normalize(source, data, *, env=None, model=None):
        return [
            FindingCreate(source_type="wiz", source_id=f"wiz-{i}", title=f"Finding {i}")
            for i in range(len(data))
        ], []

    with (
        patch(
            "cliff.integrations.ingest_worker.normalize_findings",
            side_effect=_mock_normalize,
        ),
        patch(
            "cliff.integrations.ingest_worker.create_finding",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from cliff.integrations.ingest_worker import _process_job

        await _process_job(
            db,
            job.job_id,
            env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "k"}),
            model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
        )

    progress = await get_ingest_job(db, job.job_id)
    assert progress.status == "completed"
    assert progress.completed_chunks == 3  # 8 items / 3 chunk_size = 3 chunks
    assert mock_create.call_count == 8  # 8 findings total
    await close_db()


@pytest.mark.asyncio
async def test_process_job_partial_failure():
    """Worker handles chunk failures gracefully."""
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    # Use 6 items > _SMALL_IMPORT_THRESHOLD so chunk_size=3 is preserved
    raw = [{"id": str(i)} for i in range(6)]
    job = await create_ingest_job(db, source="snyk", raw_data=raw, chunk_size=3)

    call_count = 0

    async def _mock_normalize(source, data, *, env=None, model=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM timeout")
        from cliff.models import FindingCreate

        return [
            FindingCreate(source_type="snyk", source_id=f"s-{i}", title=f"F {i}")
            for i in range(len(data))
        ], []

    with (
        patch(
            "cliff.integrations.ingest_worker.normalize_findings",
            side_effect=_mock_normalize,
        ),
        patch(
            "cliff.integrations.ingest_worker.create_finding",
            new_callable=AsyncMock,
        ),
    ):
        from cliff.integrations.ingest_worker import _process_job

        await _process_job(
            db,
            job.job_id,
            env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "k"}),
            model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
        )

    progress = await get_ingest_job(db, job.job_id)
    assert progress.status == "completed"
    assert progress.completed_chunks == 1
    assert progress.failed_chunks == 1
    assert len(progress.errors) >= 1
    await close_db()


@pytest.mark.asyncio
async def test_process_job_no_provider_marks_failed_not_retry():
    """No resolved AI provider → terminal ``failed`` (not a fail→pending→retry
    loop). The normalizer is a PA agent now and can't run without a provider."""
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import create_ingest_job, get_ingest_job

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    job = await create_ingest_job(
        db, source="wiz", raw_data=[{"id": "1"}], chunk_size=1
    )
    from cliff.integrations.ingest_worker import _process_job

    await _process_job(
        db,
        job.job_id,
        env_resolver=AsyncMock(return_value={}),  # no provider env
        model_resolver=AsyncMock(return_value=None),  # no canonical model
    )

    progress = await get_ingest_job(db, job.job_id)
    assert progress.status == "failed"
    assert progress.completed_chunks == 0
    assert any("provider" in e.lower() for e in (progress.errors or []))
    await close_db()


@pytest.mark.asyncio
async def test_process_job_cancellation():
    """Worker respects cancellation between chunks."""
    from cliff.db.connection import close_db, init_db
    from cliff.db.repo_ingest_job import (
        create_ingest_job,
        get_ingest_job,
        set_job_status,
    )

    await init_db(":memory:")
    from cliff.db.connection import _db as db

    raw = [{"id": str(i)} for i in range(6)]
    job = await create_ingest_job(db, source="wiz", raw_data=raw, chunk_size=3)

    chunk_calls = 0

    async def _mock_normalize(source, data, *, env=None, model=None):
        nonlocal chunk_calls
        chunk_calls += 1
        # Cancel after first chunk
        await set_job_status(db, job.job_id, "cancelled")
        from cliff.models import FindingCreate

        return [
            FindingCreate(source_type="wiz", source_id="x", title="t")
        ], []

    with (
        patch(
            "cliff.integrations.ingest_worker.normalize_findings",
            side_effect=_mock_normalize,
        ),
        patch(
            "cliff.integrations.ingest_worker.create_finding",
            new_callable=AsyncMock,
        ),
    ):
        from cliff.integrations.ingest_worker import _process_job

        await _process_job(
            db,
            job.job_id,
            env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "k"}),
            model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
        )

    progress = await get_ingest_job(db, job.job_id)
    assert progress.status == "cancelled"
    assert chunk_calls == 1  # Only first chunk processed
    await close_db()


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_endpoint_creates_job(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={"source": "wiz", "raw_data": [{"id": "1", "title": "test"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["total_items"] == 1
    assert body["total_chunks"] == 1
    assert body["estimated_tokens"] > 0
    assert body["poll_url"].startswith("/api/findings/ingest/")


@pytest.mark.asyncio
async def test_ingest_dry_run(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={
            "source": "snyk",
            "raw_data": [{"id": str(i)} for i in range(25)],
            "chunk_size": 10,
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "dry_run"
    assert body["job_id"] == "dry-run"
    assert body["total_items"] == 25
    assert body["total_chunks"] == 3
    assert body["estimated_tokens"] > 0


@pytest.mark.asyncio
async def test_ingest_empty_data(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={"source": "wiz", "raw_data": []},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_ingest_progress_endpoint(db_client):
    # Create a job first
    resp = await db_client.post(
        "/api/findings/ingest",
        json={"source": "wiz", "raw_data": [{"id": "1"}]},
    )
    job_id = resp.json()["job_id"]

    # Check progress
    resp = await db_client.get(f"/api/findings/ingest/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["status"] == "pending"
    assert body["completed_chunks"] == 0


@pytest.mark.asyncio
async def test_ingest_progress_not_found(db_client):
    resp = await db_client.get("/api/findings/ingest/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_endpoint(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={"source": "wiz", "raw_data": [{"id": "1"}]},
    )
    job_id = resp.json()["job_id"]

    resp = await db_client.post(f"/api/findings/ingest/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_completed_job_fails(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={"source": "wiz", "raw_data": [{"id": "1"}]},
    )
    job_id = resp.json()["job_id"]

    # Manually set to completed
    from cliff.db.connection import _db as db
    from cliff.db.repo_ingest_job import set_job_status

    await set_job_status(db, job_id, "completed")

    resp = await db_client.post(f"/api/findings/ingest/{job_id}/cancel")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_chunk_size_clamped(db_client):
    resp = await db_client.post(
        "/api/findings/ingest",
        json={
            "source": "wiz",
            "raw_data": [{"id": "1"}],
            "chunk_size": 100,  # exceeds max of 50
        },
    )
    assert resp.status_code == 200
    assert resp.json()["chunk_size"] == 50
