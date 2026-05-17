"""Tests for the MCP Gateway — config resolver (ADR-0018, Phase I-1)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from cliff.db.connection import close_db, init_db
from cliff.db.repo_integration import create_integration
from cliff.integrations.audit import AuditLogger
from cliff.integrations.gateway import MCPConfigResolver
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
async def resolver_with_audit(vault: CredentialVault, db: aiosqlite.Connection):
    audit = AuditLogger(db)
    await audit.start()
    r = MCPConfigResolver(vault, audit_logger=audit)
    yield r
    await audit.stop()


async def _create_github_integration(db: aiosqlite.Connection, vault: CredentialVault) -> str:
    """Helper: create a GitHub integration with credentials."""
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source", provider_name="GitHub"
        ),
    )
    await vault.store(integration.id, "github_personal_access_token", "ghp_test123")
    return integration.id


async def _create_jira_integration(db: aiosqlite.Connection, vault: CredentialVault) -> str:
    """Helper: create a Jira Cloud integration with credentials."""
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="ticketing", provider_name="Jira Cloud"
        ),
    )
    await vault.store(integration.id, "jira_url", "https://test.atlassian.net")
    await vault.store(integration.id, "jira_email", "user@test.com")
    await vault.store(integration.id, "jira_api_token", "ATATT3xtest")
    return integration.id


# ---------------------------------------------------------------------------
# Placeholder resolution (unit tests — no DB needed)
# ---------------------------------------------------------------------------


def test_resolve_single_placeholder():
    config = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${credential:github_personal_access_token}"},
    }
    creds = {"github_personal_access_token": "ghp_real_token"}
    result = MCPConfigResolver.resolve_placeholders(config, creds)
    assert result["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_real_token"


def test_resolve_multiple_placeholders():
    config = {
        "command": "python",
        "env": {
            "WIZ_CLIENT_ID": "${credential:wiz_client_id}",
            "WIZ_CLIENT_SECRET": "${credential:wiz_client_secret}",
        },
    }
    creds = {"wiz_client_id": "id-123", "wiz_client_secret": "secret-456"}
    result = MCPConfigResolver.resolve_placeholders(config, creds)
    assert result["env"]["WIZ_CLIENT_ID"] == "id-123"
    assert result["env"]["WIZ_CLIENT_SECRET"] == "secret-456"


def test_no_placeholders_passthrough():
    config = {
        "command": "echo",
        "env": {"STATIC_VAR": "static_value"},
    }
    result = MCPConfigResolver.resolve_placeholders(config, {})
    assert result["env"]["STATIC_VAR"] == "static_value"


def test_missing_credential_leaves_placeholder():
    config = {
        "command": "test",
        "env": {"TOKEN": "${credential:missing_key}"},
    }
    result = MCPConfigResolver.resolve_placeholders(config, {})
    assert result["env"]["TOKEN"] == "${credential:missing_key}"


def test_command_and_args_preserved():
    config = {
        "command": "npx",
        "args": ["-y", "${credential:not_a_real_placeholder}"],
        "env": {"TOKEN": "${credential:token}"},
    }
    creds = {"token": "real"}
    result = MCPConfigResolver.resolve_placeholders(config, creds)
    assert result["command"] == "npx"
    assert result["args"] == ["-y", "${credential:not_a_real_placeholder}"]
    assert result["env"]["TOKEN"] == "real"


def test_original_config_not_mutated():
    config = {"command": "test", "env": {"K": "${credential:k}"}}
    MCPConfigResolver.resolve_placeholders(config, {"k": "v"})
    assert config["env"]["K"] == "${credential:k}"


def test_no_env_section():
    config = {"command": "echo", "args": ["hello"]}
    result = MCPConfigResolver.resolve_placeholders(config, {"k": "v"})
    assert result == {"command": "echo", "args": ["hello"]}


# ---------------------------------------------------------------------------
# Full config resolution (integration tests with DB)
# ---------------------------------------------------------------------------


async def test_resolve_one_enabled_integration(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    await _create_github_integration(db, vault)
    configs = await resolver.resolve_workspace_mcp_configs(db)

    assert "github" in configs
    assert configs["github"]["command"][0] == "npx"
    assert configs["github"]["environment"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_test123"


async def test_disabled_integration_skipped(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    iid = await _create_github_integration(db, vault)
    # Disable the integration.
    await db.execute(
        "UPDATE integration_config SET enabled = 0 WHERE id = ?", (iid,)
    )
    await db.commit()

    configs = await resolver.resolve_workspace_mcp_configs(db)
    assert configs == {}


async def test_no_mcp_config_in_registry_skipped(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    """Integration for a provider with no mcp_config (e.g. Snyk = coming_soon) is skipped."""
    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source", provider_name="Snyk"
        ),
    )
    await vault.store(integration.id, "snyk_api_token", "test-token")

    configs = await resolver.resolve_workspace_mcp_configs(db)
    assert configs == {}


async def test_missing_credentials_skipped(
    resolver: MCPConfigResolver, db: aiosqlite.Connection
):
    """Integration enabled but no credentials stored -> skipped."""
    await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source", provider_name="GitHub"
        ),
    )
    configs = await resolver.resolve_workspace_mcp_configs(db)
    assert configs == {}


async def test_multiple_integrations(
    resolver: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    await _create_github_integration(db, vault)
    await _create_jira_integration(db, vault)

    configs = await resolver.resolve_workspace_mcp_configs(db)
    assert "github" in configs
    assert "jira-cloud" in configs
    assert configs["jira-cloud"]["environment"]["JIRA_API_TOKEN"] == "ATATT3xtest"


async def test_empty_when_no_integrations(
    resolver: MCPConfigResolver, db: aiosqlite.Connection
):
    configs = await resolver.resolve_workspace_mcp_configs(db)
    assert configs == {}


async def test_audit_event_emitted(
    resolver_with_audit: MCPConfigResolver, db: aiosqlite.Connection, vault: CredentialVault
):
    await _create_github_integration(db, vault)
    await resolver_with_audit.resolve_workspace_mcp_configs(db)
    await asyncio.sleep(0.1)  # Let async audit writer process

    from cliff.db import repo_audit

    events = await repo_audit.query_audit_log(db, event_type="mcp.config_resolved")
    assert len(events) == 1
    assert events[0]["provider_name"] == "GitHub"


# ---------------------------------------------------------------------------
# opencode.json integration (workspace dir manager)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_finding() -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id="finding-001",
        source_type="snyk",
        source_id="SNYK-001",
        title="Test finding",
        status="new",
        created_at=now,
        updated_at=now,
    )


def test_workspace_opencode_json_includes_mcp(tmp_path, sample_finding: Finding):
    from cliff.workspace import WorkspaceDirManager

    mgr = WorkspaceDirManager(base_dir=tmp_path)
    mcp_servers = {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
        }
    }
    ws = mgr.create("ws-mcp-test", sample_finding, mcp_servers=mcp_servers)
    config = json.loads(ws.opencode_json.read_text())

    assert "mcp" in config
    assert "github" in config["mcp"]
    assert config["mcp"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_test"
    # Permissions still present.
    assert config["permission"]["bash"] == "ask"


def test_workspace_opencode_json_no_mcp_without_servers(tmp_path, sample_finding: Finding):
    from cliff.workspace import WorkspaceDirManager

    mgr = WorkspaceDirManager(base_dir=tmp_path)
    ws = mgr.create("ws-no-mcp", sample_finding)
    config = json.loads(ws.opencode_json.read_text())

    assert "mcp" not in config
    assert config["permission"]["bash"] == "ask"


def test_workspace_opencode_json_empty_mcp_dict(tmp_path, sample_finding: Finding):
    from cliff.workspace import WorkspaceDirManager

    mgr = WorkspaceDirManager(base_dir=tmp_path)
    ws = mgr.create("ws-empty-mcp", sample_finding, mcp_servers={})
    config = json.loads(ws.opencode_json.read_text())

    # Empty dict should not produce mcp key.
    assert "mcp" not in config
