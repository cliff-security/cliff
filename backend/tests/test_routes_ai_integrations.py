"""Tests for the AI integration routes (IMPL-0011 Phase B2 / D2 / E1 / E2)."""

from __future__ import annotations

import json
import os

import httpx
import pytest

from opensec.ai import autodetect, catalog
from opensec.db.connection import close_db, init_db
from opensec.integrations.vault import CredentialVault

# ---------------------------------------------------------------------------
# Fixture: ai_client — async HTTP client with a real vault wired up
# ---------------------------------------------------------------------------


class _StubAudit:
    def __init__(self) -> None:
        self.events: list = []

    async def log(self, event) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _stub_opencode_auth_sync(monkeypatch):
    """Don't try to talk to a real OpenCode in route tests.

    ``AIIntegrationService._sync_opencode_auth`` PUTs the key into
    OpenCode's auth.json on every save; ``_live_probe`` (ADR-0037) GETs
    ``/config`` on every status read. Both no-op here so pytest-httpx
    doesn't intercept them as unmatched requests.
    """
    from unittest.mock import AsyncMock

    from opensec.engine.client import opencode_client

    monkeypatch.setattr(opencode_client, "set_auth", AsyncMock(return_value=True))
    monkeypatch.setattr(
        opencode_client, "get_config", AsyncMock(return_value={})
    )


@pytest.fixture
async def ai_client(monkeypatch, tmp_path):
    """An HTTP client wired with a real vault + stub audit logger.

    The fixture isolates autodetect to ``tmp_path`` so dev-machine envs
    don't bleed in, and clears the four sniffed env vars.
    """
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from opensec.main import app

    @asynccontextmanager
    async def _noop(_app):
        yield

    app.router.lifespan_context = _noop
    await init_db(":memory:")

    # Wire vault + audit on app.state.
    from opensec.db.connection import _db as _dbref  # type: ignore[attr-defined]
    assert _dbref is not None
    audit = _StubAudit()
    app.state.vault = CredentialVault(_dbref, key=os.urandom(32))
    app.state.audit_logger = audit

    # Make autodetect look at tmp_path, never the developer's real $HOME.
    monkeypatch.setattr(autodetect, "_home", lambda: tmp_path)
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    for provider in catalog.all_providers():
        monkeypatch.delenv(
            f"OPENSEC_AI_MODEL_OVERRIDE_{provider.upper()}", raising=False
        )
    catalog._reset_for_tests()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Attach the audit stub for assertions.
        ac.audit = audit  # type: ignore[attr-defined]
        yield ac

    app.state.vault = None
    app.state.audit_logger = None
    await close_db()


# ---------------------------------------------------------------------------
# /autodetect (GET) — Phase B2
# ---------------------------------------------------------------------------


async def test_autodetect_returns_found_false_when_nothing_present(
    ai_client,
) -> None:
    resp = await ai_client.get("/api/integrations/ai/autodetect")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "provider": None, "source": None}


async def test_autodetect_returns_provider_and_source_but_never_key(
    ai_client, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-revealed-key")
    resp = await ai_client.get("/api/integrations/ai/autodetect")
    body = resp.json()
    assert body["found"] is True
    assert body["provider"] == "anthropic"
    assert body["source"] == "ANTHROPIC_API_KEY env"
    # Most important: the raw key must not appear in the response.
    assert "sk-ant-revealed-key" not in json.dumps(body)


# ---------------------------------------------------------------------------
# /autodetect/adopt — Phase B2
# ---------------------------------------------------------------------------


async def test_adopt_returns_404_when_nothing_detected(ai_client) -> None:
    resp = await ai_client.post("/api/integrations/ai/autodetect/adopt")
    assert resp.status_code == 404


async def test_adopt_succeeds_with_valid_key(
    ai_client, monkeypatch, httpx_mock
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-valid")
    # Validator probe → 200 OK.
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    resp = await ai_client.post("/api/integrations/ai/autodetect/adopt")
    assert resp.status_code == 200
    status = resp.json()
    assert status["state"] == "connected"
    assert status["provider"] == "anthropic"
    assert status["source"] == "autodetect"


async def test_adopt_emits_audit_event_with_source_path(
    ai_client, monkeypatch, httpx_mock
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-valid")
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post("/api/integrations/ai/autodetect/adopt")
    events = [
        e for e in ai_client.audit.events if e.event_type == "ai_integration.adopt"
    ]
    assert len(events) == 1
    assert events[0].verb == "ANTHROPIC_API_KEY env"


async def test_adopt_rejects_invalid_key(ai_client, monkeypatch, httpx_mock) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bad")
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=401,
    )
    resp = await ai_client.post("/api/integrations/ai/autodetect/adopt")
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["error_code"] == "auth_failed"


# ---------------------------------------------------------------------------
# /byok — Phase D2
# ---------------------------------------------------------------------------


async def test_byok_happy_path_anthropic(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-byok"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "connected"
    assert body["provider"] == "anthropic"
    assert body["source"] == "byok"


async def test_byok_happy_path_openai(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": []},
    )
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "openai", "api_key": "sk-openai-byok"},
    )
    assert resp.status_code == 200


async def test_byok_401_surfaces_auth_failed(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=401,
    )
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-bad"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "auth_failed"


async def test_byok_network_error(ai_client, httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("network gone"))
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-x"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "network"


async def test_byok_custom_requires_base_url(ai_client) -> None:
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "custom", "api_key": "sk-x"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /status — Phase E1
# ---------------------------------------------------------------------------


async def test_status_unconfigured(ai_client) -> None:
    resp = await ai_client.get("/api/integrations/ai/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "unconfigured"
    assert body["provider"] is None


async def test_status_connected_after_byok(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-byok"},
    )
    resp = await ai_client.get("/api/integrations/ai/status")
    body = resp.json()
    assert body["state"] == "connected"
    assert body["provider"] == "anthropic"
    # Active model surfaced for the Settings card hero treatment. New default
    # in ADR-0037 is Haiku 4.5; Sonnet stays available via the picker. Post-M9
    # the response does NOT carry override_model or live_probe.
    assert body["model"] == "anthropic/claude-haiku-4-5"
    assert "override_model" not in body
    assert "live_probe" not in body


# ---------------------------------------------------------------------------
# /disconnect — Phase E2
# ---------------------------------------------------------------------------


async def test_disconnect_clears_state(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-x"},
    )
    resp = await ai_client.post("/api/integrations/ai/disconnect")
    assert resp.status_code == 204

    status_resp = await ai_client.get("/api/integrations/ai/status")
    assert status_resp.json()["state"] == "unconfigured"


async def test_disconnect_is_idempotent(ai_client) -> None:
    resp = await ai_client.post("/api/integrations/ai/disconnect")
    assert resp.status_code == 204


async def test_disconnect_emits_audit(ai_client, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-x"},
    )
    ai_client.audit.events.clear()
    await ai_client.post("/api/integrations/ai/disconnect")
    types = {e.event_type for e in ai_client.audit.events}
    assert "ai_integration.disconnect" in types


# ---------------------------------------------------------------------------
# Log-leak guard — Phase F4 (mandatory PR gate)
# ---------------------------------------------------------------------------


async def test_no_key_material_in_logs(ai_client, monkeypatch, httpx_mock, caplog) -> None:
    """Run a full BYOK + autodetect + disconnect flow and grep logs."""
    import logging

    secret = "sk-ant-NEVERLOGTHISVALUE-9f8e7d6c"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )

    with caplog.at_level(logging.DEBUG):
        await ai_client.get("/api/integrations/ai/autodetect")
        await ai_client.post("/api/integrations/ai/autodetect/adopt")
        await ai_client.get("/api/integrations/ai/status")
        await ai_client.post("/api/integrations/ai/disconnect")

    all_log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in all_log_text


# ---------------------------------------------------------------------------
# OpenAPI registration smoke test
# ---------------------------------------------------------------------------


async def test_routes_registered(ai_client) -> None:
    resp = await ai_client.get("/openapi.json")
    paths = resp.json().get("paths", {})
    assert "/api/integrations/ai/autodetect" in paths
    assert "/api/integrations/ai/autodetect/adopt" in paths
    assert "/api/integrations/ai/byok" in paths
    assert "/api/integrations/ai/status" in paths
    assert "/api/integrations/ai/disconnect" in paths


# ---------------------------------------------------------------------------
# Model picker routes (ADR-0037)
# ---------------------------------------------------------------------------


async def test_put_model_changes_canonical(ai_client, httpx_mock) -> None:
    """``PUT /model`` swaps the active model and reflects it back in /status."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-key"},
    )
    resp = await ai_client.put(
        "/api/integrations/ai/model",
        json={"model": "anthropic/claude-sonnet-4-6"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "connected"
    assert body["model"] == "anthropic/claude-sonnet-4-6"


async def test_put_model_rejects_prefix_mismatch(ai_client, httpx_mock) -> None:
    """Picker refuses to write an openai/* id while anthropic is active."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-key"},
    )
    resp = await ai_client.put(
        "/api/integrations/ai/model",
        json={"model": "openai/gpt-5"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "prefix" in body["detail"].lower()


async def test_put_model_without_active_returns_409(ai_client) -> None:
    """The picker can't fire before a provider is connected."""
    resp = await ai_client.put(
        "/api/integrations/ai/model",
        json={"model": "anthropic/claude-haiku-4-5"},
    )
    assert resp.status_code == 409


async def test_get_models_returns_catalog_for_cloud_providers(
    ai_client,
) -> None:
    """The picker fetches a curated list per cloud provider."""
    resp = await ai_client.get(
        "/api/integrations/ai/models",
        params={"provider": "anthropic"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "anthropic"
    assert body["source"] == "catalog"
    assert body["default_model"] == "anthropic/claude-haiku-4-5"
    ids = [m["id"] for m in body["models"]]
    assert "anthropic/claude-haiku-4-5" in ids
    assert "anthropic/claude-sonnet-4-6" in ids


async def test_get_models_proxies_ollama_tags(ai_client, httpx_mock) -> None:
    """Ollama's picker hits the local ``/api/tags`` and converts entries."""
    httpx_mock.add_response(
        url="http://localhost:11434/api/tags",
        method="GET",
        status_code=200,
        json={
            "models": [
                {"name": "llama3.2:latest", "size": 2_000_000_000},
                {"name": "qwen2.5-coder:7b", "size": 4_500_000_000},
            ],
        },
    )
    resp = await ai_client.get(
        "/api/integrations/ai/models",
        params={"provider": "ollama"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["source"] == "live"
    ids = [m["id"] for m in body["models"]]
    assert "ollama/llama3.2:latest" in ids
    assert "ollama/qwen2.5-coder:7b" in ids


async def test_byok_saves_google_with_gemini_env(ai_client, httpx_mock) -> None:
    """Google AI Studio BYOK round-trips and uses GEMINI_API_KEY."""
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models?key=AIzaTEST",
        method="GET",
        status_code=200,
        json={"models": []},
    )
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "google", "api_key": "AIzaTEST"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "google"
    assert body["model"] == "google/gemini-2.5-flash"


async def test_byok_saves_ollama_with_base_url(ai_client, httpx_mock) -> None:
    """Local Ollama BYOK uses base_url and skips the API-key requirement."""
    httpx_mock.add_response(
        url="http://localhost:11434/api/tags",
        method="GET",
        status_code=200,
        json={"models": [{"name": "llama3.2:latest"}]},
    )
    resp = await ai_client.post(
        "/api/integrations/ai/byok",
        json={
            "provider": "ollama",
            "api_key": "local",
            "base_url": "http://localhost:11434",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "ollama"


async def test_status_does_not_include_live_probe_or_override_model(
    ai_client, httpx_mock
) -> None:
    """Post-M9 ``GET /status`` no longer carries ``live_probe`` or
    ``override_model``. The on_key_change hook keeps the singleton's
    loaded model in lockstep with canonical state, so there is no
    separate "what's actually loaded" signal to surface."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    await ai_client.post(
        "/api/integrations/ai/byok",
        json={"provider": "anthropic", "api_key": "sk-ant-key"},
    )
    resp = await ai_client.get("/api/integrations/ai/status")
    body = resp.json()
    assert "live_probe" not in body
    assert "override_model" not in body
    # The remaining fields stay: state, provider, source, connected_at,
    # metadata, model.
    assert set(body.keys()) <= {
        "state",
        "provider",
        "source",
        "connected_at",
        "metadata",
        "model",
    }
