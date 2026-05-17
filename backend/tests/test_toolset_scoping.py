"""Tests for toolset scoping and read-only enforcement (Phase I-2, PR3).

Verifies that the gateway applies ``--toolsets`` and ``--read-only`` flags
based on the integration's ``action_tier`` and the registry entry's
``toolsets`` configuration.
"""

from __future__ import annotations

import os

import pytest

from cliff.integrations.gateway import _apply_toolset_scoping
from cliff.integrations.registry import (
    RegistryEntry,
    get_registry_entry,
)

# ---------------------------------------------------------------------------
# Registry entry tests
# ---------------------------------------------------------------------------


class TestGitHubRegistryEntry:
    """Verify the updated github.json has read-only and toolsets."""

    def test_github_has_read_only_flag(self):
        entry = get_registry_entry("github")
        assert entry is not None
        assert "--read-only" in entry.mcp_config["command"]

    def test_github_has_toolsets(self):
        entry = get_registry_entry("github")
        assert entry is not None
        assert entry.toolsets is not None
        assert "0" in entry.toolsets
        assert "1" in entry.toolsets
        assert "2" in entry.toolsets

    def test_github_tier0_toolsets(self):
        entry = get_registry_entry("github")
        assert entry.toolsets["0"] == ["repos", "code_security"]

    def test_github_tier2_toolsets(self):
        entry = get_registry_entry("github")
        assert "pull_requests" in entry.toolsets["2"]

    def test_jira_has_no_toolsets(self):
        entry = get_registry_entry("jira-cloud")
        assert entry is not None
        assert entry.toolsets is None

    def test_wiz_has_no_toolsets(self):
        entry = get_registry_entry("wiz")
        assert entry is not None
        assert entry.toolsets is None


# ---------------------------------------------------------------------------
# _apply_toolset_scoping unit tests
# ---------------------------------------------------------------------------


def _make_entry(*, toolsets=None, **kwargs) -> RegistryEntry:
    """Build a minimal RegistryEntry for testing."""
    return RegistryEntry(
        id=kwargs.get("id", "test"),
        name=kwargs.get("name", "Test"),
        adapter_type=kwargs.get("adapter_type", "finding_source"),
        description="test",
        toolsets=toolsets,
    )


class TestApplyToolsetScoping:
    """Unit tests for the _apply_toolset_scoping helper."""

    def test_tier0_appends_toolsets(self):
        config = {"args": ["-y", "pkg", "--read-only"], "env": {}}
        entry = _make_entry(toolsets={"0": ["repos", "code_security"]})
        _apply_toolset_scoping(config, entry, action_tier=0)
        assert "--toolsets" in config["args"]
        idx = config["args"].index("--toolsets")
        assert config["args"][idx + 1] == "repos,code_security"
        # --read-only stays at tier 0.
        assert "--read-only" in config["args"]

    def test_tier1_removes_read_only_and_adds_toolsets(self):
        config = {"args": ["-y", "pkg", "--read-only"], "env": {}}
        entry = _make_entry(
            toolsets={
                "0": ["repos"],
                "1": ["repos", "issues"],
            },
        )
        _apply_toolset_scoping(config, entry, action_tier=1)
        assert "--read-only" not in config["args"]
        assert "--toolsets" in config["args"]
        idx = config["args"].index("--toolsets")
        assert config["args"][idx + 1] == "repos,issues"

    def test_tier2_full_toolsets(self):
        config = {"args": ["-y", "pkg", "--read-only"], "env": {}}
        entry = _make_entry(
            toolsets={
                "0": ["repos"],
                "1": ["repos", "issues"],
                "2": ["repos", "issues", "pull_requests"],
            },
        )
        _apply_toolset_scoping(config, entry, action_tier=2)
        assert "--read-only" not in config["args"]
        idx = config["args"].index("--toolsets")
        assert config["args"][idx + 1] == "repos,issues,pull_requests"

    def test_no_toolsets_field_leaves_args_unchanged(self):
        config = {"args": ["-y", "pkg"], "env": {}}
        entry = _make_entry(toolsets=None)
        _apply_toolset_scoping(config, entry, action_tier=0)
        assert config["args"] == ["-y", "pkg"]

    def test_no_toolsets_for_tier_leaves_args_unchanged(self):
        config = {"args": ["-y", "pkg"], "env": {}}
        entry = _make_entry(toolsets={"0": ["repos"]})
        # Tier 1 not defined — no toolsets appended.
        _apply_toolset_scoping(config, entry, action_tier=1)
        assert "--toolsets" not in config["args"]

    def test_read_only_removed_even_without_toolsets(self):
        """Tier > 0 always removes --read-only, even if no toolsets defined."""
        config = {"args": ["-y", "pkg", "--read-only"], "env": {}}
        entry = _make_entry(toolsets=None)
        _apply_toolset_scoping(config, entry, action_tier=1)
        assert "--read-only" not in config["args"]

    def test_no_args_key_is_safe(self):
        config = {"env": {}}
        entry = _make_entry(toolsets={"0": ["repos"]})
        _apply_toolset_scoping(config, entry, action_tier=0)
        # Should not crash.
        assert "args" not in config


# ---------------------------------------------------------------------------
# Gateway integration test — end-to-end toolset resolution
# ---------------------------------------------------------------------------


class TestGatewayToolsetIntegration:
    """Verify that resolve_workspace applies toolset scoping."""

    @pytest.mark.asyncio
    async def test_github_tier0_gets_read_only_and_toolsets(self):
        """GitHub at tier 0 keeps --read-only and gets repos,code_security."""
        from cliff.db.connection import close_db, init_db
        from cliff.db.repo_integration import create_integration
        from cliff.integrations.gateway import MCPConfigResolver
        from cliff.integrations.vault import CredentialVault
        from cliff.models import IntegrationConfigCreate

        db = await init_db(":memory:")
        try:
            vault = CredentialVault(db, key=os.urandom(32))
            resolver = MCPConfigResolver(vault)

            gh = await create_integration(
                db,
                IntegrationConfigCreate(
                    adapter_type="finding_source",
                    provider_name="GitHub",
                    action_tier=0,
                ),
            )
            await vault.store(gh.id, "github_personal_access_token", "ghp_test")

            result = await resolver.resolve_workspace(db)
            config = result.mcp_configs["github"]
            assert "--read-only" in config["command"]
            assert "--toolsets" in config["command"]
            idx = config["command"].index("--toolsets")
            assert config["command"][idx + 1] == "repos,code_security"
        finally:
            await close_db()

    @pytest.mark.asyncio
    async def test_github_tier2_removes_read_only(self):
        """GitHub at tier 2 drops --read-only and gets full toolsets."""
        from cliff.db.connection import close_db, init_db
        from cliff.db.repo_integration import create_integration
        from cliff.integrations.gateway import MCPConfigResolver
        from cliff.integrations.vault import CredentialVault
        from cliff.models import IntegrationConfigCreate

        db = await init_db(":memory:")
        try:
            vault = CredentialVault(db, key=os.urandom(32))
            resolver = MCPConfigResolver(vault)

            gh = await create_integration(
                db,
                IntegrationConfigCreate(
                    adapter_type="finding_source",
                    provider_name="GitHub",
                    action_tier=2,
                ),
            )
            await vault.store(gh.id, "github_personal_access_token", "ghp_test")

            result = await resolver.resolve_workspace(db)
            config = result.mcp_configs["github"]
            assert "--read-only" not in config["command"]
            assert "--toolsets" in config["command"]
            idx = config["command"].index("--toolsets")
            assert "pull_requests" in config["command"][idx + 1]
        finally:
            await close_db()

    @pytest.mark.asyncio
    async def test_jira_args_unchanged(self):
        """Jira has no toolsets — args stay as-is."""
        from cliff.db.connection import close_db, init_db
        from cliff.db.repo_integration import create_integration
        from cliff.integrations.gateway import MCPConfigResolver
        from cliff.integrations.vault import CredentialVault
        from cliff.models import IntegrationConfigCreate

        db = await init_db(":memory:")
        try:
            vault = CredentialVault(db, key=os.urandom(32))
            resolver = MCPConfigResolver(vault)

            jira = await create_integration(
                db,
                IntegrationConfigCreate(
                    adapter_type="ticketing",
                    provider_name="Jira Cloud",
                ),
            )
            await vault.store(jira.id, "jira_url", "https://x.atlassian.net")
            await vault.store(jira.id, "jira_email", "a@b.com")
            await vault.store(jira.id, "jira_api_token", "tok")

            result = await resolver.resolve_workspace(db)
            config = result.mcp_configs["jira-cloud"]
            assert "--toolsets" not in config["command"]
        finally:
            await close_db()
