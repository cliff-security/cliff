"""Tests for the settings API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_model(db_client):
    """GET /api/settings/model returns current model config."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.get_config = AsyncMock(
            return_value={"model": "openai/gpt-4.1-nano"}
        )
        resp = await db_client.get("/api/settings/model")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_full_id"] == "openai/gpt-4.1-nano"
        assert data["provider"] == "openai"
        assert data["model_id"] == "gpt-4.1-nano"


@pytest.mark.asyncio
async def test_update_model(db_client, tmp_path):
    """PUT /api/settings/model updates the model."""
    with (
        patch(
            "opensec.engine.config_manager.opencode_client"
        ) as mock_client,
        patch(
            "opensec.engine.config_manager.settings"
        ) as mock_settings,
    ):
        mock_client.update_config = AsyncMock(return_value={})
        mock_client.get_config = AsyncMock(
            return_value={"model": "anthropic/claude-sonnet-4-20250514"}
        )
        mock_settings.write_opencode_config = lambda m: None
        mock_settings.opencode_model = "anthropic/claude-sonnet-4-20250514"

        resp = await db_client.put(
            "/api/settings/model",
            json={"model_full_id": "anthropic/claude-sonnet-4-20250514"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_full_id"] == "anthropic/claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_update_model_invalid_format(db_client):
    """PUT /api/settings/model rejects invalid model format."""
    resp = await db_client.put(
        "/api/settings/model",
        json={"model_full_id": "no-slash-here"},
    )
    assert resp.status_code == 400
    assert "provider/model-id" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_model_accepts_provider_and_model_id(db_client):
    """PUT /api/settings/model accepts the GET-shape ``{provider, model_id}``.

    Round-tripping the GET response is the most natural API gesture; the body
    validator should synthesize ``model_full_id`` from the parts.
    """
    with (
        patch("opensec.engine.config_manager.opencode_client") as mock_client,
        patch("opensec.engine.config_manager.settings") as mock_settings,
    ):
        mock_client.update_config = AsyncMock(return_value={})
        mock_client.get_config = AsyncMock(
            return_value={"model": "openai/gpt-5-nano"}
        )
        mock_settings.write_opencode_config = lambda m: None
        mock_settings.opencode_model = "openai/gpt-5-nano"

        resp = await db_client.put(
            "/api/settings/model",
            json={"provider": "openai", "model_id": "gpt-5-nano"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["model_full_id"] == "openai/gpt-5-nano"
        assert data["provider"] == "openai"
        assert data["model_id"] == "gpt-5-nano"


@pytest.mark.asyncio
async def test_update_model_rejects_empty_body(db_client):
    """PUT /api/settings/model with neither shape returns 422."""
    resp = await db_client.put("/api/settings/model", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_providers(db_client):
    """GET /api/settings/providers returns provider list."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.list_providers = AsyncMock(
            return_value={
                "all": [
                    {"id": "openai", "name": "OpenAI", "env": ["OPENAI_API_KEY"], "models": {}},
                ]
            }
        )
        resp = await db_client.get("/api/settings/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "openai"


@pytest.mark.asyncio
async def test_set_api_key(db_client):
    """PUT /api/settings/api-keys/{provider} stores a masked key."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.set_auth = AsyncMock(return_value=True)

        resp = await db_client.put(
            "/api/settings/api-keys/openai",
            json={"provider": "openai", "key": "sk-test1234567890ab"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["key_masked"] == "sk-...90ab"
        assert data["has_credentials"] is True
        # Full key must NOT be in response
        assert "sk-test1234567890ab" not in str(data)


@pytest.mark.asyncio
async def test_list_api_keys_masked(db_client):
    """GET /api/settings/api-keys returns DB-stored keys masked, tagged source=db."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.set_auth = AsyncMock(return_value=True)
        mock_client.get_provider_auth = AsyncMock(return_value={})

        # Store a key first
        await db_client.put(
            "/api/settings/api-keys/openai",
            json={"provider": "openai", "key": "sk-secret-key-here1"},
        )

        resp = await db_client.get("/api/settings/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["key_masked"] == "sk-...ere1"
        assert data[0]["source"] == "db"
        # Full key must NOT be in response
        assert "sk-secret-key-here1" not in str(data)


@pytest.mark.asyncio
async def test_list_api_keys_includes_env_sourced(db_client):
    """An env-sourced provider (OPENAI_API_KEY in the daemon env) must surface
    via /api-keys with source=env so users can tell the system already has a key.
    """
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        # No DB-stored keys; OpenCode reports openai is auth'd from env.
        mock_client.get_provider_auth = AsyncMock(
            return_value={"openai": [{"type": "api"}]}
        )

        resp = await db_client.get("/api/settings/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["provider"] == "openai"
        assert data[0]["source"] == "env"
        assert data[0]["key_masked"] is None
        assert data[0]["has_credentials"] is True


@pytest.mark.asyncio
async def test_list_api_keys_db_overrides_env(db_client):
    """If both DB and env have a key for the same provider, DB wins (the user
    explicitly stored it, so it takes precedence)."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.set_auth = AsyncMock(return_value=True)
        mock_client.get_provider_auth = AsyncMock(
            return_value={"openai": [{"type": "api"}]}
        )

        await db_client.put(
            "/api/settings/api-keys/openai",
            json={"provider": "openai", "key": "sk-stored-by-user-x1"},
        )

        resp = await db_client.get("/api/settings/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source"] == "db"
        assert data[0]["key_masked"] == "sk-...r-x1"


@pytest.mark.asyncio
async def test_delete_api_key(db_client):
    """DELETE /api/settings/api-keys/{provider} removes the key."""
    with patch(
        "opensec.engine.config_manager.opencode_client"
    ) as mock_client:
        mock_client.set_auth = AsyncMock(return_value=True)
        mock_client.get_provider_auth = AsyncMock(return_value={})

        # Store then delete
        await db_client.put(
            "/api/settings/api-keys/openai",
            json={"provider": "openai", "key": "sk-to-delete-12345"},
        )
        resp = await db_client.delete("/api/settings/api-keys/openai")
        assert resp.status_code == 204

        # Verify it's gone
        resp = await db_client.get("/api/settings/api-keys")
        assert resp.json() == []


@pytest.mark.asyncio
async def test_delete_api_key_not_found(db_client):
    """DELETE /api/settings/api-keys/{provider} returns 404 for missing key."""
    resp = await db_client.delete("/api/settings/api-keys/nonexistent")
    assert resp.status_code == 404


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
# Provider probe (PRD-0004 Story 4 / ADR-0031)
# ---------------------------------------------------------------------------


class _FakeSession:
    id = "probe-session-1"


def _fake_client_success(response_text: str = "OK") -> object:
    mock = AsyncMock()
    mock.create_session = AsyncMock(return_value=_FakeSession())
    mock.send_and_get_response = AsyncMock(return_value=response_text)
    return mock


def _fake_client_raising(exc: BaseException) -> object:
    mock = AsyncMock()
    mock.create_session = AsyncMock(return_value=_FakeSession())
    mock.send_and_get_response = AsyncMock(side_effect=exc)
    return mock


@pytest.mark.asyncio
async def test_provider_test_endpoint_success(db_client):
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_success("OK"),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["latency_ms"] >= 0
    assert data["error_code"] is None
    assert data["error_message"] is None


@pytest.mark.asyncio
async def test_provider_test_endpoint_empty_response_is_timeout(db_client):
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_success(""),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_provider_test_endpoint_auth_failed(db_client):
    import httpx

    response = httpx.Response(
        status_code=401,
        text="invalid api key",
        request=httpx.Request("POST", "http://test/session/x/message"),
    )
    exc = httpx.HTTPStatusError("401", request=response.request, response=response)
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_raising(exc),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "auth_failed"
    assert "api key" in data["error_message"].lower()


@pytest.mark.asyncio
async def test_provider_test_endpoint_model_not_found(db_client):
    import httpx

    response = httpx.Response(
        status_code=404,
        text="model 'gpt-4-turboo' not found",
        request=httpx.Request("POST", "http://test/session/x/message"),
    )
    exc = httpx.HTTPStatusError("404", request=response.request, response=response)
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_raising(exc),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "model_not_found"


@pytest.mark.asyncio
async def test_provider_test_endpoint_rate_limited(db_client):
    import httpx

    response = httpx.Response(
        status_code=429,
        text="rate limit exceeded, retry after 60s",
        request=httpx.Request("POST", "http://test/session/x/message"),
    )
    exc = httpx.HTTPStatusError("429", request=response.request, response=response)
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_raising(exc),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "rate_limited"


@pytest.mark.asyncio
async def test_provider_test_endpoint_timeout(db_client):
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_raising(TimeoutError()),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_provider_test_endpoint_other_error(db_client):
    with patch(
        "opensec.api.routes.settings.opencode_client",
        _fake_client_raising(RuntimeError("catastrophic lightning strike")),
    ):
        resp = await db_client.post("/api/settings/providers/test", json={})
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "other"
    assert "catastrophic lightning strike" in data["error_message"]
