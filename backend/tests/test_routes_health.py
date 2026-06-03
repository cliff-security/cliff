"""Tests for the health endpoint."""

from __future__ import annotations


def test_health_reports_in_process_substrate(client):
    """The substrate runs in-process via Pydantic AI — ``opencode`` is the
    kept-for-compat field name and is always "ok"; ``opencode_version``
    carries the PA version string."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cliff"] == "ok"
    assert data["opencode"] == "ok"
    assert data["opencode_version"].startswith("pydantic-ai")


def test_health_ai_provider_not_ready_when_env_cache_empty(client):
    """No resolved AI credential → ai_provider_ready is False."""
    from cliff.main import app

    app.state.ai_env_cache = {}
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ai_provider_ready"] is False


def test_health_ai_provider_ready_when_resolved_and_verified(client):
    """A resolved provider key that also passed its live probe → ready."""
    from cliff.main import app

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
    from cliff.main import app

    app.state.ai_env_cache = {"ANTHROPIC_API_KEY": "sk-ant-revoked"}
    app.state.ai_provider_credential_ok = False
    try:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ai_provider_ready"] is False
    finally:
        app.state.ai_env_cache = {}
