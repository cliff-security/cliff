"""Tests for the legacy api_key migration (ADR-0036 follow-up)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from opensec.ai import repo as ai_repo
from opensec.ai.legacy_migration import migrate_legacy_api_keys_once
from opensec.ai.service import AIIntegrationService
from opensec.db.connection import close_db, init_db
from opensec.integrations.vault import CredentialVault

if TYPE_CHECKING:
    import aiosqlite


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
def vault(db: aiosqlite.Connection) -> CredentialVault:
    return CredentialVault(db, key=os.urandom(32))


@pytest.fixture
def service(
    db: aiosqlite.Connection, vault: CredentialVault
) -> AIIntegrationService:
    return AIIntegrationService(db, vault)


async def _insert_legacy_row(
    db: aiosqlite.Connection,
    *,
    provider: str,
    key: str,
    updated_at: str | None = None,
) -> None:
    when = updated_at or datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO app_setting (key, value, updated_at) VALUES (?, ?, ?)",
        (
            f"api_key:{provider}",
            json.dumps({"key": key, "key_masked": f"{key[:3]}...{key[-4:]}"}),
            when,
        ),
    )
    await db.commit()


async def test_no_legacy_rows_is_noop(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    await migrate_legacy_api_keys_once(db, service)
    assert await ai_repo.get_active(db) is None


async def test_migrates_single_anthropic_row(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    await _insert_legacy_row(db, provider="anthropic", key="sk-ant-legacy")
    await migrate_legacy_api_keys_once(db, service)

    active = await ai_repo.get_active(db)
    assert active is not None
    assert active.provider == "anthropic"
    assert active.source == "byok"

    env = await service.resolve_env_for_workspace()
    assert env == {"ANTHROPIC_API_KEY": "sk-ant-legacy"}


async def test_skips_when_new_table_already_populated(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    # User already configured a provider via the new flow.
    await service.save_byok("openai", "sk-openai-new")

    # And had a legacy row from before.
    await _insert_legacy_row(db, provider="anthropic", key="sk-ant-legacy")

    await migrate_legacy_api_keys_once(db, service)

    active = await ai_repo.get_active(db)
    assert active is not None
    # New row wins — the legacy row is left in place but never adopted.
    assert active.provider == "openai"


async def test_picks_most_recent_legacy_row(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    now = datetime.now(UTC)
    await _insert_legacy_row(
        db,
        provider="openai",
        key="sk-openai-old",
        updated_at=(now - timedelta(hours=1)).isoformat(),
    )
    await _insert_legacy_row(
        db,
        provider="anthropic",
        key="sk-ant-new",
        updated_at=now.isoformat(),
    )

    await migrate_legacy_api_keys_once(db, service)

    active = await ai_repo.get_active(db)
    assert active is not None
    assert active.provider == "anthropic"


async def test_skips_unsupported_providers(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    # Gemini (google) is not in the new AIProvider literal.
    await _insert_legacy_row(db, provider="google", key="sk-google-x")

    await migrate_legacy_api_keys_once(db, service)
    assert await ai_repo.get_active(db) is None


async def test_skips_malformed_legacy_value(
    db: aiosqlite.Connection, service: AIIntegrationService
) -> None:
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO app_setting (key, value, updated_at) VALUES (?, ?, ?)",
        ("api_key:anthropic", "not-json", now),
    )
    await db.commit()

    await migrate_legacy_api_keys_once(db, service)
    assert await ai_repo.get_active(db) is None
