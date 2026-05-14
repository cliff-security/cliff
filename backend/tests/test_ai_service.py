"""Tests for AIIntegrationService (IMPL-0011 Phase A5)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from opensec.ai import catalog
from opensec.ai.service import AIIntegrationService
from opensec.db.connection import close_db, init_db
from opensec.integrations.vault import CredentialVault

if TYPE_CHECKING:
    import aiosqlite

    from opensec.integrations.audit import AuditEvent


@pytest.fixture(autouse=True)
def _reset_catalog_state():
    catalog._reset_for_tests()
    yield
    catalog._reset_for_tests()


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
def vault_key() -> bytes:
    return os.urandom(32)


@pytest.fixture
def vault(db: aiosqlite.Connection, vault_key: bytes) -> CredentialVault:
    return CredentialVault(db, key=vault_key)


class _StubAudit:
    """Captures audit events for assertions — async-compatible with AuditLogger."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.fixture
def audit() -> _StubAudit:
    return _StubAudit()


@pytest.fixture
def service(
    db: aiosqlite.Connection, vault: CredentialVault, audit: _StubAudit
) -> AIIntegrationService:
    return AIIntegrationService(db, vault, audit_logger=audit)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_active / get_status
# ---------------------------------------------------------------------------


async def test_get_active_returns_none_when_empty(service: AIIntegrationService) -> None:
    assert await service.get_active() is None


async def test_get_status_unconfigured(service: AIIntegrationService) -> None:
    status = await service.get_status()
    assert status.state == "unconfigured"
    assert status.provider is None


# ---------------------------------------------------------------------------
# save_byok
# ---------------------------------------------------------------------------


async def test_save_byok_persists_and_round_trips_key(
    service: AIIntegrationService, vault: CredentialVault
) -> None:
    record = await service.save_byok("anthropic", "sk-ant-realkey-12345")
    assert record.provider == "anthropic"
    assert record.source == "byok"

    env = await service.resolve_env_for_workspace()
    assert env == {"ANTHROPIC_API_KEY": "sk-ant-realkey-12345"}


async def test_save_byok_with_base_url_persists_metadata(
    service: AIIntegrationService,
) -> None:
    record = await service.save_byok(
        "custom", "sk-anything", base_url="https://my-llm.example/v1"
    )
    assert record.provider == "custom"
    assert record.metadata == {"base_url": "https://my-llm.example/v1"}


async def test_save_byok_emits_audit_event(
    service: AIIntegrationService, audit: _StubAudit
) -> None:
    await service.save_byok("anthropic", "sk-ant-key")
    events = [e for e in audit.events if e.event_type == "ai_integration.connect"]
    assert len(events) == 1
    assert events[0].provider_name == "ai:anthropic"
    assert events[0].verb == "byok"


# ---------------------------------------------------------------------------
# adopt_detected
# ---------------------------------------------------------------------------


async def test_adopt_detected_records_source_path(
    service: AIIntegrationService,
) -> None:
    record = await service.adopt_detected(
        "anthropic", "sk-ant-detected", "ANTHROPIC_API_KEY env"
    )
    assert record.source == "autodetect"
    assert record.metadata == {"source_path": "ANTHROPIC_API_KEY env"}


async def test_adopt_audit_event_includes_source_path(
    service: AIIntegrationService, audit: _StubAudit
) -> None:
    await service.adopt_detected(
        "anthropic", "sk-ant-detected", "~/.claude/.credentials.json"
    )
    events = [e for e in audit.events if e.event_type == "ai_integration.adopt"]
    assert len(events) == 1
    assert events[0].verb == "~/.claude/.credentials.json"


# ---------------------------------------------------------------------------
# complete_oauth
# ---------------------------------------------------------------------------


async def test_complete_oauth_stores_metadata(service: AIIntegrationService) -> None:
    record = await service.complete_oauth(
        "openrouter", "sk-or-abcd", metadata={"user_email": "a@b.co"}
    )
    assert record.provider == "openrouter"
    assert record.source == "openrouter-oauth"
    assert record.metadata == {"user_email": "a@b.co"}


# ---------------------------------------------------------------------------
# resolve_env_for_workspace
# ---------------------------------------------------------------------------


async def test_resolve_env_returns_empty_when_unconfigured(
    service: AIIntegrationService,
) -> None:
    assert await service.resolve_env_for_workspace() == {}


async def test_resolve_env_uses_correct_env_var_per_provider(
    service: AIIntegrationService,
) -> None:
    await service.save_byok("openai", "sk-openai-key")
    env = await service.resolve_env_for_workspace()
    assert env == {"OPENAI_API_KEY": "sk-openai-key"}


async def test_resolve_env_skips_empty_credential(
    service: AIIntegrationService,
) -> None:
    """A present-but-empty stored credential must not be injected — an empty
    env var still routes through OpenCode and 401s confusingly, and it makes
    the readiness gate falsely report 'ready'. (QA Q01 B06b.)"""
    await service.save_byok("anthropic", "")
    assert await service.resolve_env_for_workspace() == {}


async def test_resolve_env_propagates_byok_base_url(
    service: AIIntegrationService,
) -> None:
    """A BYOK custom endpoint is carried through as ``*_BASE_URL`` — the
    pool scrubs host-inherited base URLs (QA Q01 B07), so this is the only
    path that gets a user's custom endpoint to the subprocess."""
    await service.save_byok(
        "anthropic", "sk-ant-key", base_url="https://proxy.internal/v1"
    )
    env = await service.resolve_env_for_workspace()
    assert env == {
        "ANTHROPIC_API_KEY": "sk-ant-key",
        "ANTHROPIC_BASE_URL": "https://proxy.internal/v1",
    }


# ---------------------------------------------------------------------------
# resolve_model_for_workspace
# ---------------------------------------------------------------------------


async def test_resolve_model_returns_none_when_unconfigured(
    service: AIIntegrationService,
) -> None:
    assert await service.resolve_model_for_workspace() is None


async def test_resolve_model_returns_provider_default(
    service: AIIntegrationService,
) -> None:
    """With no ``model`` app-setting chosen, the provider's catalog
    default is used."""
    await service.save_byok("anthropic", "sk-ant-realkey-12345")
    assert (
        await service.resolve_model_for_workspace()
        == "anthropic/claude-sonnet-4-6"
    )


async def test_resolve_model_prefers_app_setting_model(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """The user's chosen active model (``model`` app-setting) wins over the
    catalog default when its provider matches the active integration.
    (QA Q01 B07: workspace was provisioned for sonnet while the user had
    selected haiku.)"""
    from opensec.db.repo_setting import upsert_setting

    await service.save_byok("anthropic", "sk-ant-realkey-12345")
    await upsert_setting(db, "model", {"full_id": "anthropic/claude-haiku-4-5"})
    assert (
        await service.resolve_model_for_workspace()
        == "anthropic/claude-haiku-4-5"
    )


async def test_resolve_model_ignores_app_setting_from_other_provider(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """A ``model`` app-setting left over from a different provider must not
    be handed to a workspace whose injected key is for another provider —
    fall back to the active provider's catalog default."""
    from opensec.db.repo_setting import upsert_setting

    await service.save_byok("anthropic", "sk-ant-realkey-12345")
    await upsert_setting(db, "model", {"full_id": "openai/gpt-5"})
    assert (
        await service.resolve_model_for_workspace()
        == "anthropic/claude-sonnet-4-6"
    )


# ---------------------------------------------------------------------------
# Reconnect / replace
# ---------------------------------------------------------------------------


async def test_save_byok_replaces_prior_row_for_same_provider(
    service: AIIntegrationService,
) -> None:
    await service.save_byok("anthropic", "sk-ant-first")
    await service.save_byok("anthropic", "sk-ant-second")

    env = await service.resolve_env_for_workspace()
    assert env == {"ANTHROPIC_API_KEY": "sk-ant-second"}


async def test_switching_providers_replaces_active(
    service: AIIntegrationService,
) -> None:
    await service.save_byok("anthropic", "sk-ant-key")
    await service.save_byok("openrouter", "sk-or-key")

    active = await service.get_active()
    assert active is not None
    assert active.provider == "openrouter"


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


async def test_disconnect_clears_state(service: AIIntegrationService) -> None:
    await service.save_byok("anthropic", "sk-ant-key")
    removed = await service.disconnect()
    assert removed is True
    assert await service.get_active() is None
    assert await service.resolve_env_for_workspace() == {}


async def test_disconnect_is_idempotent(service: AIIntegrationService) -> None:
    assert await service.disconnect() is False  # nothing to remove


async def test_disconnect_emits_audit_event(
    service: AIIntegrationService, audit: _StubAudit
) -> None:
    await service.save_byok("anthropic", "sk-ant-key")
    await service.disconnect()
    events = [e for e in audit.events if e.event_type == "ai_integration.disconnect"]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Status with override
# ---------------------------------------------------------------------------


async def test_get_status_surfaces_active_override(
    service: AIIntegrationService, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")
    await service.save_byok("anthropic", "sk-ant-key")
    status = await service.get_status()
    assert status.state == "connected"
    assert status.override_model == "claude-opus-4-1"


# ---------------------------------------------------------------------------
# OpenCode auth.json sync
# ---------------------------------------------------------------------------


async def test_save_byok_pushes_key_to_opencode_auth(
    service: AIIntegrationService, monkeypatch
) -> None:
    """OpenCode 1.3.x reads auth.json over env vars — verify we push."""
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    push = AsyncMock(return_value=True)
    monkeypatch.setattr(opencode_client, "set_auth", push)

    await service.save_byok("anthropic", "sk-ant-push-target")

    push.assert_awaited_once_with(
        "anthropic", {"type": "api", "key": "sk-ant-push-target"}
    )


async def test_save_byok_does_not_push_for_custom_provider(
    service: AIIntegrationService, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    push = AsyncMock(return_value=True)
    monkeypatch.setattr(opencode_client, "set_auth", push)

    await service.save_byok("custom", "sk-x", base_url="https://x.example/v1")

    push.assert_not_awaited()


async def test_disconnect_clears_opencode_auth(
    service: AIIntegrationService, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    push = AsyncMock(return_value=True)
    monkeypatch.setattr(opencode_client, "set_auth", push)

    await service.save_byok("openrouter", "sk-or-disc")
    push.reset_mock()
    await service.disconnect()

    # Called once with empty key after disconnect.
    push.assert_awaited_once_with(
        "openrouter", {"type": "api", "key": ""}
    )


async def test_save_byok_survives_opencode_unavailable(
    service: AIIntegrationService, monkeypatch
) -> None:
    """The new flow must still persist if OpenCode is unreachable."""
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    push = AsyncMock(side_effect=RuntimeError("opencode down"))
    monkeypatch.setattr(opencode_client, "set_auth", push)

    record = await service.save_byok("anthropic", "sk-ant-key")
    assert record.provider == "anthropic"


async def test_get_status_no_override_returns_none(
    service: AIIntegrationService,
) -> None:
    await service.save_byok("anthropic", "sk-ant-key")
    status = await service.get_status()
    assert status.override_model is None
