"""Tests for the integration audit logger (ADR-0017)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from cliff.db import repo_audit
from cliff.db.connection import close_db, init_db
from cliff.integrations.audit import (
    AuditEvent,
    AuditLogger,
    hash_parameters,
)

if TYPE_CHECKING:
    import aiosqlite


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def audit_logger(db: aiosqlite.Connection):
    logger = AuditLogger(db)
    await logger.start()
    yield logger
    await logger.stop()


def _make_event(**overrides) -> AuditEvent:
    defaults = {
        "event_type": "integration.create",
        "status": "success",
    }
    defaults.update(overrides)
    return AuditEvent(**defaults)


# ---------------------------------------------------------------------------
# Hash computation (parameter hashing only)
# ---------------------------------------------------------------------------


def test_hash_parameters_dict():
    h = hash_parameters({"key": "value"})
    assert h is not None and len(h) == 64


def test_hash_parameters_string():
    h = hash_parameters("raw-param-string")
    assert h is not None and len(h) == 64


def test_hash_parameters_none():
    assert hash_parameters(None) is None


# ---------------------------------------------------------------------------
# Event writing
# ---------------------------------------------------------------------------


async def test_log_event_writes_to_db(audit_logger: AuditLogger, db: aiosqlite.Connection):
    await audit_logger.log(_make_event(event_type="integration.create"))
    # Give the background writer a moment to process.
    await asyncio.sleep(0.1)

    events = await repo_audit.query_audit_log(db)
    assert len(events) == 1
    assert events[0]["event_type"] == "integration.create"
    assert events[0]["status"] == "success"


# ---------------------------------------------------------------------------
# Query filters
# ---------------------------------------------------------------------------


async def test_query_by_workspace(audit_logger: AuditLogger, db: aiosqlite.Connection):
    await audit_logger.log(_make_event(workspace_id="ws-1"))
    await audit_logger.log(_make_event(workspace_id="ws-2"))
    await asyncio.sleep(0.1)

    results = await repo_audit.query_audit_log(db, workspace_id="ws-1")
    assert len(results) == 1
    assert results[0]["workspace_id"] == "ws-1"


async def test_query_by_integration(audit_logger: AuditLogger, db: aiosqlite.Connection):
    await audit_logger.log(_make_event(integration_id="int-a"))
    await audit_logger.log(_make_event(integration_id="int-b"))
    await asyncio.sleep(0.1)

    results = await repo_audit.query_audit_log(db, integration_id="int-a")
    assert len(results) == 1


async def test_query_by_event_type(audit_logger: AuditLogger, db: aiosqlite.Connection):
    await audit_logger.log(_make_event(event_type="credential.store"))
    await audit_logger.log(_make_event(event_type="integration.delete"))
    await asyncio.sleep(0.1)

    results = await repo_audit.query_audit_log(db, event_type="credential.store")
    assert len(results) == 1
    assert results[0]["event_type"] == "credential.store"


async def test_query_pagination(audit_logger: AuditLogger, db: aiosqlite.Connection):
    for i in range(10):
        await audit_logger.log(_make_event(event_type=f"evt_{i}"))
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)

    page1 = await repo_audit.query_audit_log(db, limit=3, offset=0)
    page2 = await repo_audit.query_audit_log(db, limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 3
    # Pages should not overlap (newest first).
    ids1 = {e["id"] for e in page1}
    ids2 = {e["id"] for e in page2}
    assert ids1.isdisjoint(ids2)


async def test_count_audit_events(audit_logger: AuditLogger, db: aiosqlite.Connection):
    for _ in range(5):
        await audit_logger.log(_make_event())
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)

    total = await repo_audit.count_audit_events(db)
    assert total == 5


# ---------------------------------------------------------------------------
# Parameters hashing
# ---------------------------------------------------------------------------


async def test_parameters_stored_as_hash(audit_logger: AuditLogger, db: aiosqlite.Connection):
    param_hash = hash_parameters({"api_key": "ghp_secret123"})
    await audit_logger.log(_make_event(parameters_hash=param_hash))
    await asyncio.sleep(0.1)

    events = await repo_audit.query_audit_log(db)
    # Raw value must never appear.
    assert "ghp_secret123" not in str(events[0])
    assert events[0]["parameters_hash"] == param_hash


# ---------------------------------------------------------------------------
# Async queue behavior
# ---------------------------------------------------------------------------


async def test_async_queue_processing(db: aiosqlite.Connection):
    """Events logged before start() are processed once start() is called."""
    logger = AuditLogger(db)
    # Log before starting — event goes into queue.
    await logger.log(_make_event(event_type="early_event"))
    assert await repo_audit.count_audit_events(db) == 0  # Not yet written

    await logger.start()
    await asyncio.sleep(0.15)

    assert await repo_audit.count_audit_events(db) == 1
    await logger.stop()


async def test_queue_full_fallback_sync(db: aiosqlite.Connection):
    """When the queue is full, events are written synchronously (not dropped)."""
    logger = AuditLogger(db, max_queue_size=1)
    # Don't start the writer — queue will fill up immediately.
    await logger.log(_make_event(event_type="first"))  # Fills queue
    await logger.log(_make_event(event_type="overflow"))  # Should write sync

    # At least the overflow event should be in the DB (sync fallback).
    count = await repo_audit.count_audit_events(db)
    assert count >= 1


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------


async def test_cleanup_old_events(audit_logger: AuditLogger, db: aiosqlite.Connection):
    await audit_logger.log(_make_event())
    await asyncio.sleep(0.1)

    # Backdate the event to make it "old".
    await db.execute("UPDATE audit_log SET timestamp = '2020-01-01T00:00:00'")
    await db.commit()

    deleted = await repo_audit.cleanup_old_events(db, retention_days=1)
    assert deleted == 1
    assert await repo_audit.count_audit_events(db) == 0


# ---------------------------------------------------------------------------
# API endpoint (via TestClient)
# ---------------------------------------------------------------------------


async def test_audit_api_endpoint(db: aiosqlite.Connection):
    """GET /api/audit returns events."""
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan

    # Initialize audit logger on app.state
    logger = AuditLogger(db)
    await logger.start()
    app.state.audit_logger = logger

    await logger.log(_make_event(event_type="integration.create", integration_id="int-x"))
    await asyncio.sleep(0.1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/audit", params={"integration_id": "int-x"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["events"][0]["event_type"] == "integration.create"

    await logger.stop()
