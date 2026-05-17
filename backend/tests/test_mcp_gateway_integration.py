"""Integration tests for the full MCP gateway flow (Phase I-1 PR 3).

These tests exercise the complete flow from integration creation through
workspace creation to config verification — without needing a real OpenCode
binary. They validate that all Phase I-1 components work together.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from cliff.db.connection import close_db, init_db
from cliff.db.repo_integration import create_integration, update_integration
from cliff.integrations.audit import AuditLogger
from cliff.integrations.gateway import MCPConfigResolver
from cliff.integrations.vault import CredentialVault
from cliff.models import FindingCreate, IntegrationConfigCreate, IntegrationConfigUpdate

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


# ---------------------------------------------------------------------------
# Full gateway flow (integration test)
# ---------------------------------------------------------------------------


async def test_full_gateway_flow(db: aiosqlite.Connection, vault: CredentialVault, tmp_path):
    """End-to-end: create integration → store creds → create workspace → verify everything."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db import repo_audit
    from cliff.db.repo_finding import create_finding
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    audit = AuditLogger(db)
    await audit.start()
    resolver = MCPConfigResolver(vault, audit_logger=audit)

    # 1. Create integration + credentials via repo layer.
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source", provider_name="GitHub"
        ),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_e2e_test_token")

    # 2. Create a finding.
    finding = await create_finding(
        db,
        FindingCreate(
            source_type="cliff-dogfooding",
            source_id="OSSEC-E2E",
            title="E2E test finding",
        ),
    )

    # 3. Create workspace (triggers MCP config resolution).
    dir_mgr = WorkspaceDirManager(base_dir=tmp_path)
    tmpl = AgentTemplateEngine()
    builder = WorkspaceContextBuilder(dir_mgr, tmpl, mcp_resolver=resolver)
    workspace = await builder.create_workspace(db, finding)

    # 4. Verify opencode.json has MCP section.
    ws_dir = tmp_path / workspace.id
    oc_config = json.loads((ws_dir / "opencode.json").read_text())
    assert "mcp" in oc_config
    assert "github" in oc_config["mcp"]
    assert oc_config["mcp"]["github"]["command"][0] == "npx"
    gh_env = oc_config["mcp"]["github"]["environment"]
    assert gh_env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_e2e_test_token"
    # Permissions still present.
    assert oc_config["permission"]["bash"] == "ask"

    # 5. Verify workspace-integrations.json manifest.
    manifest = json.loads((ws_dir / "workspace-integrations.json").read_text())
    assert len(manifest) == 1
    assert manifest[0]["provider_name"] == "GitHub"
    assert manifest[0]["registry_id"] == "github"
    assert manifest[0]["action_tier"] == 0
    assert "collect" in manifest[0]["capabilities"]
    assert manifest[0]["status"] == "connected"

    # 6. Verify audit log has mcp.config_resolved event.
    await asyncio.sleep(0.1)  # Let async writer flush.
    events = await repo_audit.query_audit_log(db, event_type="mcp.config_resolved")
    assert len(events) == 1
    assert events[0]["provider_name"] == "GitHub"
    assert events[0]["integration_id"] == integration.id

    # 7. Config freshness should be fresh.
    freshness = await resolver.check_config_freshness(db, str(ws_dir))
    assert freshness.stale is False

    await audit.stop()


# ---------------------------------------------------------------------------
# Config freshness tests
# ---------------------------------------------------------------------------


async def test_config_fresh_when_unchanged(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Config is fresh when nothing has changed since workspace creation."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    resolver = MCPConfigResolver(vault)
    integration = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_fresh")

    finding = await create_finding(
        db, FindingCreate(source_type="test", source_id="F-1", title="Fresh test"),
    )
    builder = WorkspaceContextBuilder(
        WorkspaceDirManager(base_dir=tmp_path),
        AgentTemplateEngine(),
        mcp_resolver=resolver,
    )
    workspace = await builder.create_workspace(db, finding)

    result = await resolver.check_config_freshness(db, str(tmp_path / workspace.id))
    assert result.stale is False


async def test_config_stale_when_integration_added(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Config becomes stale when a new integration is added after workspace creation."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    resolver = MCPConfigResolver(vault)

    # Create workspace with GitHub only.
    gh = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(gh.id, "github_personal_access_token", "ghp_stale1")

    finding = await create_finding(
        db, FindingCreate(source_type="test", source_id="F-2", title="Stale test"),
    )
    builder = WorkspaceContextBuilder(
        WorkspaceDirManager(base_dir=tmp_path),
        AgentTemplateEngine(),
        mcp_resolver=resolver,
    )
    workspace = await builder.create_workspace(db, finding)

    # Now add Jira integration.
    jira = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="ticketing", provider_name="Jira Cloud"),
    )
    await vault.store(jira.id, "jira_url", "https://test.atlassian.net")
    await vault.store(jira.id, "jira_email", "user@test.com")
    await vault.store(jira.id, "jira_api_token", "ATATT3x")

    result = await resolver.check_config_freshness(db, str(tmp_path / workspace.id))
    assert result.stale is True
    assert "added" in result.reason.lower() or "new" in result.reason.lower()


async def test_config_stale_when_integration_disabled(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Config becomes stale when an integration is disabled after workspace creation."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    resolver = MCPConfigResolver(vault)
    gh = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(gh.id, "github_personal_access_token", "ghp_stale2")

    finding = await create_finding(
        db, FindingCreate(source_type="test", source_id="F-3", title="Disable test"),
    )
    builder = WorkspaceContextBuilder(
        WorkspaceDirManager(base_dir=tmp_path),
        AgentTemplateEngine(),
        mcp_resolver=resolver,
    )
    workspace = await builder.create_workspace(db, finding)

    # Disable the integration.
    await update_integration(db, gh.id, IntegrationConfigUpdate(enabled=False))

    result = await resolver.check_config_freshness(db, str(tmp_path / workspace.id))
    assert result.stale is True
    assert "removed" in result.reason.lower() or "disabled" in result.reason.lower()


async def test_config_stale_when_tier_changed(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """Config becomes stale when an integration's action tier is changed."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    resolver = MCPConfigResolver(vault)
    gh = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(gh.id, "github_personal_access_token", "ghp_tier")

    finding = await create_finding(
        db, FindingCreate(source_type="test", source_id="F-4", title="Tier test"),
    )
    builder = WorkspaceContextBuilder(
        WorkspaceDirManager(base_dir=tmp_path),
        AgentTemplateEngine(),
        mcp_resolver=resolver,
    )
    workspace = await builder.create_workspace(db, finding)

    # Change action tier.
    await update_integration(db, gh.id, IntegrationConfigUpdate(action_tier=2))

    result = await resolver.check_config_freshness(db, str(tmp_path / workspace.id))
    assert result.stale is True
    assert "tier" in result.reason.lower()


async def test_config_fresh_no_manifest_no_integrations(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """No manifest + no integrations = fresh (nothing to do)."""
    resolver = MCPConfigResolver(vault)
    # Create an empty workspace dir (no manifest).
    ws_dir = tmp_path / "empty-ws"
    ws_dir.mkdir()

    result = await resolver.check_config_freshness(db, str(ws_dir))
    assert result.stale is False


# ---------------------------------------------------------------------------
# API integration test with freshness
# ---------------------------------------------------------------------------


async def test_integrations_api_includes_freshness(
    db: aiosqlite.Connection, vault: CredentialVault, tmp_path
):
    """GET /workspaces/{id}/integrations returns config_stale field."""
    from cliff.agents.template_engine import AgentTemplateEngine
    from cliff.db.repo_finding import create_finding
    from cliff.main import app
    from cliff.workspace.context_builder import WorkspaceContextBuilder
    from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.audit_logger = None
    app.state.vault = vault
    app.state.process_pool = AsyncMock()

    resolver = MCPConfigResolver(vault)
    gh = await create_integration(
        db,
        IntegrationConfigCreate(adapter_type="finding_source", provider_name="GitHub"),
    )
    await vault.store(gh.id, "github_personal_access_token", "ghp_api_fresh")

    finding = await create_finding(
        db, FindingCreate(source_type="test", source_id="F-API", title="API fresh test"),
    )
    builder = WorkspaceContextBuilder(
        WorkspaceDirManager(base_dir=tmp_path),
        AgentTemplateEngine(),
        mcp_resolver=resolver,
    )
    app.state.context_builder = builder
    workspace = await builder.create_workspace(db, finding)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/workspaces/{workspace.id}/integrations")
        assert resp.status_code == 200
        data = resp.json()

        assert "integrations" in data
        assert "config_stale" in data
        assert data["config_stale"] is False
        assert len(data["integrations"]) == 1
        assert data["integrations"][0]["provider_name"] == "GitHub"
