"""Tests for the /api/version handshake endpoint."""

from __future__ import annotations


def test_version_returns_handshake(client):
    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    # All four fields are required by the CLI handshake.
    assert data["cliff"]
    assert data["opencode"]
    assert data["schema_version"] == "1"
    assert data["min_cli"]


def test_version_cliff_matches_version_file(client):
    """The cliff field should reflect the VERSION file at the repo root."""
    from cliff.config import settings

    resp = client.get("/api/version")
    assert resp.json()["cliff"] == settings.cliff_version


def test_version_opencode_matches_pinned_engine(client):
    """The opencode field should reflect .opencode-version."""
    from cliff.config import settings

    resp = client.get("/api/version")
    assert resp.json()["opencode"] == settings.opencode_version
