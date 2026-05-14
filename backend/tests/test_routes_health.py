"""Tests for the health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock


def test_health_opencode_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["opensec"] == "ok"
    assert data["opencode"] == "ok"


def test_health_opencode_down(client, mock_opencode_process):
    mock_opencode_process.health_check = AsyncMock(return_value=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["opensec"] == "ok"
    assert data["opencode"] == "unavailable"


def test_health_ai_provider_not_ready_when_env_cache_empty(client):
    """No resolved AI credential → ai_provider_ready is False."""
    from opensec.main import app

    app.state.ai_env_cache = {}
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ai_provider_ready"] is False


def test_health_ai_provider_ready_when_resolved_and_verified(client):
    """A resolved provider key that also passed its live probe → ready."""
    from opensec.main import app

    app.state.ai_env_cache = {"ANTHROPIC_API_KEY": "sk-ant-xxx"}
    app.state.ai_provider_credential_ok = True
    try:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ai_provider_ready"] is True
    finally:
        app.state.ai_env_cache = {}
        app.state.ai_provider_credential_ok = False


def test_health_ai_provider_not_ready_when_credential_unverified(client):
    """Q01-B02 — a present-but-revoked key resolves into the env cache fine
    but fails its live probe; ai_provider_ready must read False, not True."""
    from opensec.main import app

    app.state.ai_env_cache = {"ANTHROPIC_API_KEY": "sk-ant-revoked"}
    app.state.ai_provider_credential_ok = False
    try:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ai_provider_ready"] is False
    finally:
        app.state.ai_env_cache = {}
