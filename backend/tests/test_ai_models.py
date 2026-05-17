"""Tests for the AI provider Pydantic models (IMPL-0011 Phase A2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensec.ai.models import (
    AIIntegration,
    AIIntegrationCreate,
    AIStatus,
    BYOKRequest,
    DetectedKey,
    ValidationResult,
)


def test_ai_integration_round_trip() -> None:
    payload = {
        "id": "id-1",
        "integration_id": "int-1",
        "provider": "openrouter",
        "source": "openrouter-oauth",
        "metadata": {"user_email": "a@b.co"},
        "connected_at": "2026-05-11T10:00:00+00:00",
        "last_validated_at": None,
        "created_at": "2026-05-11T10:00:00+00:00",
        "updated_at": "2026-05-11T10:00:00+00:00",
    }
    model = AIIntegration(**payload)
    assert model.provider == "openrouter"
    assert model.source == "openrouter-oauth"
    assert model.metadata == {"user_email": "a@b.co"}


def test_ai_integration_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        AIIntegration(
            id="id-1",
            integration_id="int-1",
            provider="bogus",  # type: ignore[arg-type]
            source="byok",
            connected_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
        )


def test_ai_integration_repr_hides_anything_keylike() -> None:
    model = AIIntegration(
        id="id-1",
        integration_id="int-1",
        provider="anthropic",
        source="byok",
        connected_at="2026-05-11T10:00:00+00:00",
        created_at="2026-05-11T10:00:00+00:00",
        updated_at="2026-05-11T10:00:00+00:00",
    )
    text = repr(model)
    # Nothing key-looking should appear; the repr is intentionally minimal.
    assert "api_key" not in text
    assert "sk-" not in text


def test_ai_status_unconfigured() -> None:
    status = AIStatus(state="unconfigured")
    assert status.state == "unconfigured"
    assert status.provider is None


def test_ai_status_connected_includes_provider_and_model() -> None:
    """Post-M9: canonical model is the single AIStatus model field;
    ``override_model`` and ``live_probe`` are removed."""
    status = AIStatus(
        state="connected",
        provider="openrouter",
        source="openrouter-oauth",
        connected_at="2026-05-11T10:00:00+00:00",
        metadata={"user_email": "a@b.co"},
        model="openrouter/anthropic/claude-haiku-4-5",
    )
    assert status.state == "connected"
    assert status.model == "openrouter/anthropic/claude-haiku-4-5"


def test_detected_key_repr_never_includes_raw_key() -> None:
    detected = DetectedKey(
        provider="anthropic",
        source="ANTHROPIC_API_KEY env",
        raw_key="sk-ant-supersecret-xyz",
    )
    text = repr(detected)
    assert "sk-ant-supersecret-xyz" not in text
    assert "<redacted>" in text


def test_byok_request_repr_redacts_key() -> None:
    body = BYOKRequest(provider="anthropic", api_key="sk-ant-abcdefg")
    text = repr(body)
    assert "sk-ant-abcdefg" not in text


def test_byok_request_rejects_empty_key() -> None:
    with pytest.raises(ValidationError):
        BYOKRequest(provider="anthropic", api_key="")


def test_validation_result_error_shape() -> None:
    result = ValidationResult(
        ok=False, error_code="auth_failed", error_message="rejected"
    )
    assert result.ok is False
    assert result.error_code == "auth_failed"


def test_ai_integration_create_minimal() -> None:
    create = AIIntegrationCreate(provider="anthropic", source="byok")
    assert create.provider == "anthropic"
    assert create.metadata is None
