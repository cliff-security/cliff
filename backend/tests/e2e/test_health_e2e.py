"""E2E: Health endpoint with real OpenCode."""

from __future__ import annotations


def test_health_returns_ok(app_client):
    resp = app_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cliff"] == "ok"
    assert data["opencode"] == "ok"
    assert data["model"]  # non-empty model name


def test_health_shows_version(app_client):
    resp = app_client.get("/health")
    data = resp.json()
    version = data["opencode_version"]
    assert version
    assert "." in version  # looks like semver
