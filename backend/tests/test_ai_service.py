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


@pytest.fixture(autouse=True)
def _isolate_opencode_client(monkeypatch):
    """Stub ``opencode_client.set_auth`` / ``get_config`` so tests can't
    reach a running OpenCode singleton on the dev host.

    Without this, ``service.save_byok`` calls ``_sync_opencode_auth`` →
    ``opencode_client.set_auth("openrouter", {"key": "sk-or-key"})``,
    which on a dev box with a real ``:8001`` daemon up CLOBBERS the
    user's OAuth-issued key in OpenCode's ``auth.json``. Re-tested by
    running ``pytest tests/test_ai_service.py`` against a live daemon
    and seeing the test placeholders show up in ``~/.local/share/
    opencode/auth.json``.

    Individual tests that need to assert on ``set_auth`` call shape can
    override with their own ``monkeypatch.setattr``.
    """
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    monkeypatch.setattr(opencode_client, "set_auth", AsyncMock(return_value=True))
    monkeypatch.setattr(
        opencode_client, "get_config", AsyncMock(return_value={})
    )


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
        == "anthropic/claude-haiku-4-5"
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
    # ``save_byok`` (ADR-0037) writes ``app_setting(model)`` atomically.
    # We then clobber it with a stale openai value to simulate the
    # cross-provider drift the test guards against.
    await upsert_setting(db, "model", {"full_id": "openai/gpt-5"})
    assert (
        await service.resolve_model_for_workspace()
        == "anthropic/claude-haiku-4-5"
    )


# ---------------------------------------------------------------------------
# verify_active_credential (Q01-B02)
# ---------------------------------------------------------------------------


async def test_verify_active_credential_none_when_unconfigured(
    service: AIIntegrationService,
) -> None:
    assert await service.verify_active_credential() is None


async def test_verify_active_credential_ok_stamps_last_validated(
    service: AIIntegrationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live probe that passes returns ok and stamps last_validated_at."""
    from opensec.ai.models import ValidationResult

    async def _fake_validate(*_args, **_kwargs) -> ValidationResult:
        return ValidationResult(ok=True)

    monkeypatch.setattr(
        "opensec.ai.service.validators.validate", _fake_validate
    )
    await service.save_byok("anthropic", "sk-ant-realkey-12345")
    assert await service.get_active() is not None
    assert (await service.get_active()).last_validated_at is None

    result = await service.verify_active_credential()
    assert result is not None
    assert result.ok is True
    # last_validated_at is now stamped on the integration row.
    assert (await service.get_active()).last_validated_at is not None


async def test_verify_active_credential_surfaces_auth_failure(
    service: AIIntegrationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked/wrong key resolves fine but the probe rejects it — the
    auth_failed verdict is surfaced and last_validated_at stays unstamped."""
    from opensec.ai.models import ValidationResult

    async def _fake_validate(*_args, **_kwargs) -> ValidationResult:
        return ValidationResult(
            ok=False,
            error_code="auth_failed",
            error_message="rejected",
        )

    monkeypatch.setattr(
        "opensec.ai.service.validators.validate", _fake_validate
    )
    await service.save_byok("anthropic", "sk-ant-revoked")

    result = await service.verify_active_credential()
    assert result is not None
    assert result.ok is False
    assert result.error_code == "auth_failed"
    assert (await service.get_active()).last_validated_at is None


async def test_verify_active_credential_network_error_is_not_auth_failed(
    service: AIIntegrationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient probe failure is surfaced as ``network`` — callers must
    be able to tell it apart from a definitive auth rejection so readiness
    doesn't flap on a flaky probe."""
    from opensec.ai.models import ValidationResult

    async def _fake_validate(*_args, **_kwargs) -> ValidationResult:
        return ValidationResult(ok=False, error_code="network")

    monkeypatch.setattr(
        "opensec.ai.service.validators.validate", _fake_validate
    )
    await service.save_byok("anthropic", "sk-ant-realkey-12345")

    result = await service.verify_active_credential()
    assert result is not None
    assert result.error_code == "network"
    assert result.error_code != "auth_failed"


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


# M9: ``override_model`` field was removed from AIStatus per architect
# health-check (one canonical state, one read). The env override stays as
# a dev escape hatch (``catalog.resolve_model``) but is no longer surfaced
# on the wire. The tests for it are no longer applicable.


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


# ---------------------------------------------------------------------------
# ADR-0037 — canonical state, set_model, drift, Ollama, Google
# ---------------------------------------------------------------------------


async def test_save_byok_writes_canonical_model_from_catalog_default(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """A fresh BYOK save sets app_setting(model) to the provider's default
    so workspace spawn + Settings UI see the same value (ADR-0037)."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok("anthropic", "sk-ant-key")
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-haiku-4-5"}


async def test_save_byok_with_explicit_model_overrides_default(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """An explicit model argument wins over the catalog default."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok(
        "anthropic", "sk-ant-key", model="anthropic/claude-opus-4-1"
    )
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-opus-4-1"}


async def test_save_byok_explicit_model_without_prefix_gets_prefixed(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """Caller-supplied model without ``provider/`` gets the prefix added."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok("anthropic", "sk-ant-key", model="claude-opus-4-1")
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-opus-4-1"}


async def test_save_byok_with_mismatched_prefix_ignores_explicit_model(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """An explicit model whose prefix doesn't match the provider falls back
    to the catalog default (the wrong-namespace value is the bug we're
    catching, not the value we propagate)."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok(
        "anthropic", "sk-ant-key", model="openai/gpt-5"
    )
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-haiku-4-5"}


async def test_save_byok_preserves_prior_user_choice_on_reconnect(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """Reconnecting the same provider keeps the user's stored model.

    Anthropic-on-Sonnet user re-saves the integration — they should stay
    on Sonnet, not get reset to the new Haiku default. (Migration
    rule from ADR-0037.)"""
    from opensec.db.repo_setting import get_setting, upsert_setting

    await upsert_setting(
        db, "model", {"full_id": "anthropic/claude-sonnet-4-6"}
    )
    await service.save_byok("anthropic", "sk-ant-key")
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-sonnet-4-6"}


async def test_switching_providers_falls_to_new_provider_default(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """Switching anthropic → openrouter rewrites app_setting(model) to the
    new provider's default — the old stored model's prefix is stale."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok("anthropic", "sk-ant-key")
    await service.save_byok("openrouter", "sk-or-key")
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "openrouter/anthropic/claude-haiku-4.5"}


async def test_set_model_rejects_unprefixed_id(
    service: AIIntegrationService,
) -> None:
    """``set_model`` insists on an explicit provider prefix."""
    from opensec.ai.service import ModelPrefixMismatchError

    await service.save_byok("anthropic", "sk-ant-key")
    with pytest.raises(ModelPrefixMismatchError):
        await service.set_model("claude-haiku-4-5")  # missing prefix


async def test_set_model_rejects_prefix_mismatch(
    service: AIIntegrationService,
) -> None:
    """``set_model`` refuses to write an openai/* id when anthropic is active."""
    from opensec.ai.service import ModelPrefixMismatchError

    await service.save_byok("anthropic", "sk-ant-key")
    with pytest.raises(ModelPrefixMismatchError):
        await service.set_model("openai/gpt-5")


async def test_set_model_without_active_provider_raises(
    service: AIIntegrationService,
) -> None:
    """Picker can't fire before a provider exists — fail loudly."""
    from opensec.ai.service import NoActiveProviderError

    with pytest.raises(NoActiveProviderError):
        await service.set_model("anthropic/claude-haiku-4-5")


async def test_set_model_updates_canonical(
    service: AIIntegrationService, db: aiosqlite.Connection
) -> None:
    """Happy path: the picker writes the new model."""
    from opensec.db.repo_setting import get_setting

    await service.save_byok("anthropic", "sk-ant-key")
    await service.set_model("anthropic/claude-sonnet-4-6")
    stored = await get_setting(db, "model")
    assert stored is not None
    assert stored.value == {"full_id": "anthropic/claude-sonnet-4-6"}


async def test_set_model_fires_on_key_change(
    db: aiosqlite.Connection, vault: CredentialVault
) -> None:
    """``set_model`` triggers the singleton-restart hook so OpenCode picks
    up the new opencode.json model without waiting for the next save."""
    seen: list[dict[str, str]] = []

    async def hook(env: dict[str, str]) -> None:
        seen.append(env)

    service = AIIntegrationService(db, vault, on_key_change=hook)
    await service.save_byok("anthropic", "sk-ant-key")
    seen.clear()
    await service.set_model("anthropic/claude-sonnet-4-6")
    assert len(seen) == 1
    assert seen[0].get("ANTHROPIC_API_KEY") == "sk-ant-key"


async def test_resolve_env_for_ollama_injects_base_url_no_key(
    service: AIIntegrationService,
) -> None:
    """Ollama has no API key — the env should carry ``OLLAMA_BASE_URL``
    only (default to localhost when the user didn't override it)."""
    await service.save_byok("ollama", "local")
    env = await service.resolve_env_for_workspace()
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert env.get("OLLAMA_BASE_URL") == "http://localhost:11434"


async def test_resolve_env_for_ollama_honors_custom_base_url(
    service: AIIntegrationService,
) -> None:
    """A user with Ollama on a non-default port (e.g. via SSH tunnel) sees
    their base URL flow through to the workspace env."""
    await service.save_byok(
        "ollama", "local", base_url="http://10.0.0.5:11434"
    )
    env = await service.resolve_env_for_workspace()
    assert env == {"OLLAMA_BASE_URL": "http://10.0.0.5:11434"}


async def test_resolve_env_for_google_uses_gemini_env_var(
    service: AIIntegrationService,
) -> None:
    """Google AI Studio reads ``GEMINI_API_KEY`` (not ``GOOGLE_API_KEY``)."""
    await service.save_byok("google", "AIzaSyTESTKEY")
    env = await service.resolve_env_for_workspace()
    assert env == {"GEMINI_API_KEY": "AIzaSyTESTKEY"}


async def test_save_byok_for_ollama_skips_opencode_auth_push(
    service: AIIntegrationService, monkeypatch
) -> None:
    """Ollama doesn't authenticate — the auth.json push is a no-op."""
    seen: list[tuple[str, dict]] = []

    class _StubClient:
        async def set_auth(self, opencode_id: str, payload: dict) -> None:
            seen.append((opencode_id, payload))

    monkeypatch.setattr(
        "opensec.engine.client.opencode_client", _StubClient()
    )
    await service.save_byok("ollama", "local", base_url="http://localhost:11434")
    # No push for ollama.
    assert seen == []


async def test_get_status_returns_canonical_model_post_save(
    service: AIIntegrationService,
) -> None:
    """Post-M9: ``get_status`` is the single read. It returns the
    canonical model from ``app_setting(model)`` (resolved via
    ``_resolve_canonical_model``) — no separate live probe of OpenCode,
    no drift signal. ``on_key_change`` guarantees the singleton's
    loaded model matches the canonical write before the next request.
    """
    await service.save_byok("anthropic", "sk-ant-key")
    status = await service.get_status()
    assert status.state == "connected"
    assert status.model == "anthropic/claude-haiku-4-5"
