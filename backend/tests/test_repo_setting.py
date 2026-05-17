"""Tests for the AppSetting repository."""

from __future__ import annotations

import pytest

from cliff.db.repo_setting import delete_setting, get_setting, list_settings, upsert_setting


@pytest.mark.asyncio
async def test_upsert_and_get(db_client):
    """Upserting a setting stores and retrieves it."""
    from cliff.db.connection import _db as db

    result = await upsert_setting(db, "test_key", {"hello": "world"})
    assert result.key == "test_key"
    assert result.value == {"hello": "world"}

    fetched = await get_setting(db, "test_key")
    assert fetched is not None
    assert fetched.value == {"hello": "world"}


@pytest.mark.asyncio
async def test_upsert_overwrites(db_client):
    """Upserting the same key overwrites the value."""
    from cliff.db.connection import _db as db

    await upsert_setting(db, "model", {"full_id": "openai/gpt-4"})
    await upsert_setting(db, "model", {"full_id": "anthropic/claude-sonnet-4-20250514"})

    fetched = await get_setting(db, "model")
    assert fetched is not None
    assert fetched.value["full_id"] == "anthropic/claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_get_nonexistent(db_client):
    """Getting a nonexistent key returns None."""
    from cliff.db.connection import _db as db

    result = await get_setting(db, "does_not_exist")
    assert result is None


@pytest.mark.asyncio
async def test_list_with_prefix(db_client):
    """Listing with a prefix filters by key prefix."""
    from cliff.db.connection import _db as db

    await upsert_setting(db, "api_key:openai", {"key": "sk-abc"})
    await upsert_setting(db, "api_key:anthropic", {"key": "sk-ant"})
    await upsert_setting(db, "model", {"full_id": "openai/gpt-4"})

    api_keys = await list_settings(db, prefix="api_key:")
    assert len(api_keys) == 2
    assert all(s.key.startswith("api_key:") for s in api_keys)

    all_settings = await list_settings(db)
    assert len(all_settings) == 3


@pytest.mark.asyncio
async def test_delete(db_client):
    """Deleting a setting removes it."""
    from cliff.db.connection import _db as db

    await upsert_setting(db, "to_delete", {"x": 1})
    assert await delete_setting(db, "to_delete") is True
    assert await get_setting(db, "to_delete") is None


@pytest.mark.asyncio
async def test_delete_nonexistent(db_client):
    """Deleting a nonexistent key returns False."""
    from cliff.db.connection import _db as db

    assert await delete_setting(db, "nope") is False
