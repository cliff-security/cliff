"""Tests for workspace integrations API, permission tiers, and manifest (Phase I-1 PR 2)."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from cliff.db.connection import close_db, init_db
from cliff.db.repo_integration import create_integration
from cliff.integrations.gateway import MCPConfigResolver
from cliff.integrations.registry import get_registry_entry, load_registry
from cliff.integrations.vault import CredentialVault
from cliff.models import Finding, IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite

TEST_KEY = os.urandom(32)


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def vault(db: aiosqlite.Connection):
    return CredentialVault(db, key=TEST_KEY)


@pytest.fixture
async def resolver(vault: CredentialVault):
    return MCPConfigResolver(vault)


@pytest.fixture
def sample_finding() -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id="finding-ws-int",
        source_type="snyk",
        source_id="SNYK-001",
        title="Test finding for workspace integrations",
        status="new",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Action tier in registry
# ---------------------------------------------------------------------------


def test_jira_default_action_tier():
    entry = get_registry_entry("jira-cloud")
    assert entry is not None
    assert entry.default_action_tier == 1  # Enrichment (creates issues)


def test_github_default_action_tier():
    entry = get_registry_entry("github")
    assert entry is not None
    assert entry.default_action_tier == 0  # Read-only


def test_all_entries_have_action_tier():
    entries = load_registry()
    for entry in entries:
        assert isinstance(entry.default_action_tier, int)
        assert 0 <= entry.default_action_tier <= 2


# ---------------------------------------------------------------------------
# Action tier in integration_config
# ---------------------------------------------------------------------------


async def test_create_integration_with_action_tier(db: aiosqlite.Connection):
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="ticketing",
            provider_name="Jira Cloud",
            action_tier=1,
        ),
    )
    assert integration.action_tier == 1


async def test_create_integration_default_action_tier(db: aiosqlite.Connection):
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="GitHub",
        ),
    )
    assert integration.action_tier == 0


# ---------------------------------------------------------------------------
# Workspace manifest (resolve_workspace)
# ---------------------------------------------------------------------------


async def test_resolve_workspace_returns_integrations(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    integration = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_test")

    result = await resolver.resolve_workspace(db)
    assert len(result.integrations) == 1
    ws_int = result.integrations[0]
    assert ws_int.integration_id == integration.id
    assert ws_int.provider_name == "GitHub"
    assert ws_int.registry_id == "github"
    assert ws_int.action_tier == 0
    assert "collect" in ws_int.capabilities


async def test_resolve_workspace_respects_action_tier(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="ticketing",
            provider_name="Jira Cloud",
            action_tier=2,  # User overrides to mutation
        ),
    )
    await vault.store(integration.id, "jira_url", "https://test.atlassian.net")
    await vault.store(integration.id, "jira_email", "user@test.com")
    await vault.store(integration.id, "jira_api_token", "ATATT3xtest")

    result = await resolver.resolve_workspace(db)
    assert len(result.integrations) == 1
    assert result.integrations[0].action_tier == 2


# ---------------------------------------------------------------------------
# Manifest written to workspace dir
# ---------------------------------------------------------------------------


async def test_manifest_written_during_workspace_creation(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path, sample_finding: Finding
):
    """Create a workspace with integrations and verify the manifest exists."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.integrations.gateway import MCPConfigResolver
    from cliff.models import FindingCreate
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    # Setup: create finding + integration + credentials.
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="test", source_id="T-1", title="Test finding",
        ),
    )
    integration = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_manifest_test")

    resolver = MCPConfigResolver(vault)
    dir_mgr = WorkspaceDirManager(base_dir=tmp_path)
    tmpl = AgentTemplateEngine()
    builder = WorkspaceContextBuilder(dir_mgr, tmpl, mcp_resolver=resolver)

    workspace = await builder.create_workspace(db, finding)

    # Verify manifest exists.
    manifest_path = tmp_path / workspace.id / "workspace-integrations.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert len(manifest) == 1
    assert manifest[0]["provider_name"] == "GitHub"
    assert manifest[0]["registry_id"] == "github"
    assert manifest[0]["action_tier"] == 0
    assert "collect" in manifest[0]["capabilities"]

    # Verify opencode.json also has mcp section.
    oc_config = json.loads((tmp_path / workspace.id / "opencode.json").read_text())
    assert "mcp" in oc_config
    assert "github" in oc_config["mcp"]


async def test_no_manifest_without_integrations(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Workspace without integrations should not have a manifest file."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.integrations.gateway import MCPConfigResolver
    from cliff.models import FindingCreate
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    finding = await create_finding(
        db,
        FindingCreate(source_type="test", source_id="T-2", title="No integrations"),
    )

    resolver = MCPConfigResolver(vault)
    dir_mgr = WorkspaceDirManager(base_dir=tmp_path)
    tmpl = AgentTemplateEngine()
    builder = WorkspaceContextBuilder(dir_mgr, tmpl, mcp_resolver=resolver)

    workspace = await builder.create_workspace(db, finding)
    manifest_path = tmp_path / workspace.id / "workspace-integrations.json"
    assert not manifest_path.exists()


# ---------------------------------------------------------------------------
# API endpoint: GET /workspaces/{id}/integrations
# ---------------------------------------------------------------------------


async def test_workspace_integrations_api(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Full API flow: create workspace with integration, query integrations endpoint."""
    from unittest.mock import AsyncMock

    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.integrations.gateway import MCPConfigResolver
    from cliff.main import app
    from cliff.models import FindingCreate
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = vault
    app.state.process_pool = AsyncMock()

    # Setup workspace with integration.
    finding = await create_finding(
        db,
        FindingCreate(source_type="test", source_id="T-API", title="API test"),
    )
    integration = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_api_test")

    resolver = MCPConfigResolver(vault)
    dir_mgr = WorkspaceDirManager(base_dir=tmp_path)
    tmpl = AgentTemplateEngine()
    builder = WorkspaceContextBuilder(dir_mgr, tmpl, mcp_resolver=resolver)
    app.state.context_builder = builder

    workspace = await builder.create_workspace(db, finding)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/workspaces/{workspace.id}/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["integrations"]) == 1
        assert data["integrations"][0]["provider_name"] == "GitHub"
        assert data["integrations"][0]["action_tier"] == 0
        assert data["integrations"][0]["status"] == "connected"
        assert "config_stale" in data


async def test_workspace_integrations_api_empty(db: aiosqlite.Connection, tmp_path):
    """Workspace with no integrations returns empty list."""
    from unittest.mock import AsyncMock

    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.main import app
    from cliff.models import FindingCreate
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = None
    app.state.process_pool = AsyncMock()

    finding = await create_finding(
        db,
        FindingCreate(source_type="test", source_id="T-EMPTY", title="Empty test"),
    )
    dir_mgr = WorkspaceDirManager(base_dir=tmp_path)
    tmpl = AgentTemplateEngine()
    builder = WorkspaceContextBuilder(dir_mgr, tmpl)
    app.state.context_builder = builder

    workspace = await builder.create_workspace(db, finding)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/workspaces/{workspace.id}/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["integrations"] == []
        assert data["config_stale"] is False


async def test_workspace_integrations_api_404(db: aiosqlite.Connection):
    """Non-existent workspace returns 404."""
    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/workspaces/nonexistent/integrations")
        assert resp.status_code == 404
