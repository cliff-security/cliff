"""Tests for the settings API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cliff.main import app

# ---------------------------------------------------------------------------
# Model (ADR-0037 — canonical AI state, no OpenCode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_model_no_provider_returns_empty(db_client):
    """GET /api/settings/model with no provider connected → empty config."""
    resp = await db_client.get("/api/settings/model")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_full_id"] == ""
    assert data["provider"] == ""
    assert data["model_id"] == ""


@pytest.mark.asyncio
async def test_get_model_returns_canonical(db_client):
    """GET /api/settings/model splits the canonical id into parts."""
    app.state.vault = object()
    try:
        with patch(
            "cliff.ai.service.AIIntegrationService.resolve_model_for_workspace",
            AsyncMock(return_value="openai/gpt-4.1-nano"),
        ):
            resp = await db_client.get("/api/settings/model")
    finally:
        app.state.vault = None
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_full_id"] == "openai/gpt-4.1-nano"
    assert data["provider"] == "openai"
    assert data["model_id"] == "gpt-4.1-nano"


@pytest.mark.asyncio
async def test_update_model_requires_vault(db_client):
    """PUT /api/settings/model with no credential vault → 503."""
    resp = await db_client.put(
        "/api/settings/model",
        json={"model_full_id": "anthropic/claude-haiku-4-5"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_update_model_sets_canonical(db_client):
    """PUT /api/settings/model routes through set_model and echoes the id."""
    app.state.vault = object()
    try:
        with patch(
            "cliff.ai.service.AIIntegrationService.set_model",
            AsyncMock(return_value="anthropic/claude-haiku-4-5"),
        ):
            resp = await db_client.put(
                "/api/settings/model",
                json={"model_full_id": "anthropic/claude-haiku-4-5"},
            )
    finally:
        app.state.vault = None
    assert resp.status_code == 200, resp.text
    assert resp.json()["model_full_id"] == "anthropic/claude-haiku-4-5"


@pytest.mark.asyncio
async def test_update_model_accepts_provider_and_model_id(db_client):
    """PUT accepts the GET-shape ``{provider, model_id}`` and synthesizes the id.

    Round-tripping the GET response is the most natural API gesture; the body
    validator synthesizes ``model_full_id`` from the parts.
    """
    app.state.vault = object()
    try:
        with patch(
            "cliff.ai.service.AIIntegrationService.set_model",
            AsyncMock(return_value="openai/gpt-5-nano"),
        ):
            resp = await db_client.put(
                "/api/settings/model",
                json={"provider": "openai", "model_id": "gpt-5-nano"},
            )
    finally:
        app.state.vault = None
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["model_full_id"] == "openai/gpt-5-nano"
    assert data["provider"] == "openai"
    assert data["model_id"] == "gpt-5-nano"


@pytest.mark.asyncio
async def test_update_model_invalid_format(db_client):
    """A model id without a '/' is rejected with 400 (set_model's prefix check)."""
    app.state.vault = object()
    try:
        resp = await db_client.put(
            "/api/settings/model",
            json={"model_full_id": "no-slash-here"},
        )
    finally:
        app.state.vault = None
    assert resp.status_code == 400
    assert "provider/model" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_model_no_active_provider(db_client):
    """set_model raising NoActiveProviderError → 400."""
    from cliff.ai.service import NoActiveProviderError

    app.state.vault = object()
    try:
        with patch(
            "cliff.ai.service.AIIntegrationService.set_model",
            AsyncMock(side_effect=NoActiveProviderError("no active provider")),
        ):
            resp = await db_client.put(
                "/api/settings/model",
                json={"model_full_id": "anthropic/claude-haiku-4-5"},
            )
    finally:
        app.state.vault = None
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_model_rejects_empty_body(db_client):
    """PUT /api/settings/model with neither shape returns 422."""
    resp = await db_client.put("/api/settings/model", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Providers (catalog-derived, no OpenCode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_providers(db_client):
    """GET /api/settings/providers returns the static catalog as ``ProviderInfo``."""
    resp = await db_client.get("/api/settings/providers")
    assert resp.status_code == 200
    data = resp.json()
    ids = {p["id"] for p in data}
    assert {"openrouter", "anthropic", "openai", "google", "ollama", "custom"} <= ids

    openai = next(p for p in data if p["id"] == "openai")
    assert openai["name"] == "OpenAI"
    assert openai["env"] == ["OPENAI_API_KEY"]
    # Models are keyed by the bare id so ``f"{provider}/{model_id}"`` round-trips
    # back to the full picker id the UI and CLI rebuild.
    assert "gpt-5" in openai["models"]
    assert openai["models"]["gpt-5"]["id"] == "gpt-5"
    assert openai["models"]["gpt-5"]["name"]

    # Keyless provider (Ollama) → empty env list.
    ollama = next(p for p in data if p["id"] == "ollama")
    assert ollama["env"] == []


# --- Integrations ---


@pytest.mark.asyncio
async def test_integrations_crud(db_client):
    """Full CRUD lifecycle for integrations."""
    # Create
    resp = await db_client.post(
        "/api/settings/integrations",
        json={"adapter_type": "finding_source", "provider_name": "Snyk"},
    )
    assert resp.status_code == 201
    integration = resp.json()
    assert integration["adapter_type"] == "finding_source"
    assert integration["provider_name"] == "Snyk"
    assert integration["enabled"] is True
    integration_id = integration["id"]

    # List
    resp = await db_client.get("/api/settings/integrations")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Update
    resp = await db_client.put(
        f"/api/settings/integrations/{integration_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Delete
    resp = await db_client.delete(f"/api/settings/integrations/{integration_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await db_client.get("/api/settings/integrations")
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Provider probe (PRD-0004 Story 4 / ADR-0031) — now a Pydantic AI round-trip
# ---------------------------------------------------------------------------


def _raising_model(exc: BaseException):
    """A ``FunctionModel`` whose generation step raises *exc*."""
    from pydantic_ai.models.function import FunctionModel

    def _fn(messages, info):
        raise exc

    return FunctionModel(_fn)


@pytest.mark.asyncio
async def test_provider_test_endpoint_success(db_client):
    from pydantic_ai.models.test import TestModel

    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            return_value=TestModel(),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["latency_ms"] >= 0
    assert data["error_code"] is None
    assert data["error_message"] is None


@pytest.mark.asyncio
async def test_provider_test_endpoint_no_vault_is_other(db_client):
    """No credential vault → graceful ``other`` result, not a crash."""
    resp = await db_client.post("/api/settings/providers/test", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "other"


@pytest.mark.asyncio
async def test_provider_test_endpoint_auth_failed(db_client):
    from pydantic_ai.exceptions import ModelHTTPError

    exc = ModelHTTPError(status_code=401, model_name="x", body="invalid api key")
    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            return_value=_raising_model(exc),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "auth_failed"


@pytest.mark.asyncio
async def test_provider_test_endpoint_model_not_found(db_client):
    from pydantic_ai.exceptions import ModelHTTPError

    exc = ModelHTTPError(status_code=404, model_name="x", body="model not found")
    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            return_value=_raising_model(exc),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "model_not_found"


@pytest.mark.asyncio
async def test_provider_test_endpoint_rate_limited(db_client):
    from pydantic_ai.exceptions import ModelHTTPError

    exc = ModelHTTPError(status_code=429, model_name="x", body="rate limit exceeded")
    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            return_value=_raising_model(exc),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "rate_limited"


@pytest.mark.asyncio
async def test_provider_test_endpoint_timeout(db_client):
    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            return_value=_raising_model(TimeoutError()),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_provider_test_endpoint_provider_misconfigured_is_other(db_client):
    """A ``ProviderConfigurationError`` from build_model → graceful ``other``."""
    from cliff.agents.runtime.provider import ProviderConfigurationError

    app.state.vault = object()
    try:
        with patch(
            "cliff.agents.runtime.provider.build_model",
            side_effect=ProviderConfigurationError("no api key configured"),
        ):
            resp = await db_client.post("/api/settings/providers/test", json={})
    finally:
        app.state.vault = None
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "other"
    assert "api key" in data["error_message"].lower()
