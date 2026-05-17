"""Tests for the ai_integration repository (IMPL-0011 Phase A3)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from cliff.ai import repo as ai_repo
from cliff.db import repo_integration
from cliff.db.connection import close_db, init_db
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def _new_integration_row(
    db: aiosqlite.Connection, *, provider_name: str
) -> str:
    integration = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="ai_provider",
            provider_name=provider_name,
            enabled=True,
            config=None,
            action_tier=0,
        ),
    )
    return integration.id


async def test_create_inserts_and_returns_record(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="openrouter")
    record = await ai_repo.create(
        db,
        integration_id=integration_id,
        provider="openrouter",
        source="openrouter-oauth",
        metadata={"user_email": "a@b.co"},
    )
    assert record.id
    assert record.integration_id == integration_id
    assert record.provider == "openrouter"
    assert record.metadata == {"user_email": "a@b.co"}
    assert record.connected_at
    assert record.last_validated_at is None


async def test_get_active_returns_none_when_empty(db: aiosqlite.Connection) -> None:
    assert await ai_repo.get_active(db) is None


async def test_get_active_returns_most_recent(db: aiosqlite.Connection) -> None:
    integration_a = await _new_integration_row(db, provider_name="anthropic")
    await ai_repo.create(
        db, integration_id=integration_a, provider="anthropic", source="byok"
    )
    # Tiny sleep to ensure distinct ISO timestamps under coarse clocks.
    await asyncio.sleep(0.01)
    integration_b = await _new_integration_row(db, provider_name="openrouter")
    await ai_repo.create(
        db,
        integration_id=integration_b,
        provider="openrouter",
        source="openrouter-oauth",
    )

    record = await ai_repo.get_active(db)
    assert record is not None
    assert record.provider == "openrouter"


async def test_get_by_provider(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="anthropic")
    await ai_repo.create(
        db, integration_id=integration_id, provider="anthropic", source="byok"
    )
    record = await ai_repo.get_by_provider(db, "anthropic")
    assert record is not None
    assert record.integration_id == integration_id

    assert await ai_repo.get_by_provider(db, "openai") is None


async def test_update_last_validated_sets_timestamp(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="anthropic")
    await ai_repo.create(
        db, integration_id=integration_id, provider="anthropic", source="byok"
    )
    record = await ai_repo.update_last_validated(db, integration_id)
    assert record is not None
    assert record.last_validated_at is not None


async def test_delete_removes_row(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="anthropic")
    await ai_repo.create(
        db, integration_id=integration_id, provider="anthropic", source="byok"
    )
    assert await ai_repo.delete(db, integration_id) is True
    assert await ai_repo.get_by_integration_id(db, integration_id) is None


async def test_delete_returns_false_when_missing(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="anthropic")
    assert await ai_repo.delete(db, integration_id) is False


async def test_cascade_when_integration_config_deleted(db: aiosqlite.Connection) -> None:
    integration_id = await _new_integration_row(db, provider_name="anthropic")
    await ai_repo.create(
        db, integration_id=integration_id, provider="anthropic", source="byok"
    )
    deleted = await repo_integration.delete_integration(db, integration_id)
    assert deleted is True
    assert await ai_repo.get_by_integration_id(db, integration_id) is None
