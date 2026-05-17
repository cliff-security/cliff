"""Tests for the integration registry (Phase I-0)."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from cliff.db.connection import close_db, init_db
from cliff.integrations.registry import (
    RegistryEntry,
    get_registry_entry,
    load_registry,
)

if TYPE_CHECKING:
    import aiosqlite


def test_load_registry_returns_entries():
    entries = load_registry()
    assert len(entries) >= 6


def test_registry_entry_schema_valid():
    entries = load_registry()
    for entry in entries:
        assert isinstance(entry, RegistryEntry)
        assert entry.id
        assert entry.name
        assert entry.adapter_type
        assert entry.description


def test_get_entry_by_id():
    entry = get_registry_entry("github")
    assert entry is not None
    assert entry.name == "GitHub"
    assert entry.status == "available"


def test_get_entry_not_found():
    entry = get_registry_entry("nonexistent")
    assert entry is None


def test_credentials_schema_present():
    entries = load_registry()
    for entry in entries:
        assert isinstance(entry.credentials_schema, list)
        assert len(entry.credentials_schema) > 0, f"{entry.id} has no credentials_schema"
        for field in entry.credentials_schema:
            assert field.key_name
            assert field.label


def test_setup_guide_not_empty():
    entries = load_registry()
    for entry in entries:
        assert entry.setup_guide_md, f"{entry.id} has empty setup_guide_md"


def test_capabilities_present():
    entries = load_registry()
    for entry in entries:
        assert isinstance(entry.capabilities, list)
        assert len(entry.capabilities) > 0, f"{entry.id} has no capabilities"


def test_github_entry_has_mcp_config():
    entry = get_registry_entry("github")
    assert entry is not None
    assert entry.mcp_config is not None
    assert "command" in entry.mcp_config


def test_coming_soon_entries():
    entries = load_registry()
    coming_soon = [e for e in entries if e.status == "coming_soon"]
    assert len(coming_soon) >= 3  # wiz, snyk, sonarqube, tenable


def test_load_registry_returns_module_level_list(monkeypatch):
    """Verify load_registry() returns the module-level REGISTRY list."""
    import cliff.integrations.registry as reg

    fake = [RegistryEntry(id="fake", name="Fake", adapter_type="validation", description="test")]
    monkeypatch.setattr(reg, "REGISTRY", fake)
    assert load_registry() is fake


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def test_registry_api_list(db: aiosqlite.Connection):
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/settings/integrations/registry")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 6
        # Check structure
        entry = data[0]
        assert "id" in entry
        assert "name" in entry
        assert "credentials_schema" in entry


async def test_registry_api_single(db: aiosqlite.Connection):
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/settings/integrations/registry/github")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "github"
        assert data["name"] == "GitHub"

        # 404 for unknown entry
        resp2 = await ac.get("/api/settings/integrations/registry/nonexistent")
        assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# Credential + integration wire-up tests
# ---------------------------------------------------------------------------


async def test_credential_store_and_list(db: aiosqlite.Connection):
    """Store a credential via API, verify it appears in list (no value exposed)."""
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault
    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan

    test_key = os.urandom(32)
    app.state.vault = CredentialVault(db, key=test_key)
    audit_logger = AuditLogger(db)
    await audit_logger.start()
    app.state.audit_logger = audit_logger

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create an integration first
        resp = await ac.post(
            "/api/settings/integrations",
            json={"adapter_type": "finding_source", "provider_name": "TestProvider"},
        )
        assert resp.status_code == 201
        iid = resp.json()["id"]

        # Store credential
        resp2 = await ac.post(
            f"/api/settings/integrations/{iid}/credentials",
            json={"key_name": "api_token", "value": "ghp_test123"},
        )
        assert resp2.status_code == 201
        cred = resp2.json()
        assert cred["key_name"] == "api_token"
        assert "ghp_test123" not in json.dumps(cred)  # Value must not be exposed

        # List credentials
        resp3 = await ac.get(f"/api/settings/integrations/{iid}/credentials")
        assert resp3.status_code == 200
        creds = resp3.json()
        assert len(creds) == 1
        assert creds[0]["key_name"] == "api_token"

        # Test connection
        resp4 = await ac.post(f"/api/settings/integrations/{iid}/test")
        assert resp4.status_code == 200
        assert resp4.json()["success"] is True

    await audit_logger.stop()


async def test_integration_delete_cascades_credentials(db: aiosqlite.Connection):
    """Deleting an integration should clean up its credentials."""
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.integrations.vault import CredentialVault
    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan

    test_key = os.urandom(32)
    app.state.vault = CredentialVault(db, key=test_key)
    app.state.audit_logger = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create integration + credential
        resp = await ac.post(
            "/api/settings/integrations",
            json={"adapter_type": "finding_source", "provider_name": "Deletable"},
        )
        iid = resp.json()["id"]
        await ac.post(
            f"/api/settings/integrations/{iid}/credentials",
            json={"key_name": "secret", "value": "s3cr3t"},
        )

        # Delete integration
        resp_del = await ac.delete(f"/api/settings/integrations/{iid}")
        assert resp_del.status_code == 204

        # Credential should be gone (integration no longer exists -> 404)
        resp_creds = await ac.get(f"/api/settings/integrations/{iid}/credentials")
        assert resp_creds.status_code == 404
