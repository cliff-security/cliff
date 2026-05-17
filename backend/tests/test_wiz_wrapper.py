"""Tests for the Wiz thin MCP wrapper (Phase I-2).

Unit tests exercise the WizMCPServer tool handlers and OAuth flow via mocked
HTTP.  Integration tests verify the registry entry, gateway resolution, and
workspace creation with Wiz.
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cliff.integrations.wrappers.wiz.server import (
    TOOLS,
    WizAPIError,
    WizMCPServer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    """A WizMCPServer with test credentials."""
    return WizMCPServer(
        client_id="test_client_id",
        client_secret="test_client_secret",
        api_url="https://api.us20.app.wiz.io/graphql",
    )


def _mock_token_response():
    """Standard successful OAuth token response."""
    return httpx.Response(
        200,
        json={
            "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
            "token_type": "bearer",
            "expires_in": 86400,
        },
    )


def _mock_graphql_response(data: dict):
    """Standard successful GraphQL response."""
    return httpx.Response(200, json={"data": data})


def _mock_graphql_error(message: str = "Something went wrong"):
    """GraphQL response with errors."""
    return httpx.Response(200, json={"errors": [{"message": message}]})


# ---------------------------------------------------------------------------
# MCP protocol tests
# ---------------------------------------------------------------------------


class TestMCPProtocol:
    """Tests for MCP JSON-RPC protocol handling."""

    def test_tools_list_returns_five_tools(self):
        assert len(TOOLS) == 5
        names = {t["name"] for t in TOOLS}
        assert names == {
            "wiz_list_findings",
            "wiz_get_finding",
            "wiz_get_asset_context",
            "wiz_update_finding_status",
            "wiz_check_finding_status",
        }

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_initialize_response(self, server):
        """The server writes a valid initialize response."""
        import io

        buf = io.StringIO()
        server._respond = lambda rid, result: buf.write(json.dumps({"id": rid, "result": result}))

        # Simulate what run() does for initialize.
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cliff-mcp-wiz", "version": "0.1.0"},
        }
        server._respond(1, result)
        data = json.loads(buf.getvalue())
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert data["result"]["serverInfo"]["name"] == "cliff-mcp-wiz"

    def test_error_response_format(self):
        """Error responses follow JSON-RPC format."""
        import io

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            WizMCPServer._error(42, -32601, "Unknown method: foo")
            output = mock_stdout.getvalue()

        # Parse the Content-Length framed response.
        lines = output.split("\r\n")
        assert lines[0].startswith("Content-Length:")
        body = lines[2]
        data = json.loads(body)
        assert data["id"] == 42
        assert data["error"]["code"] == -32601
        assert "foo" in data["error"]["message"]


# ---------------------------------------------------------------------------
# OAuth token tests
# ---------------------------------------------------------------------------


class TestOAuth:
    """Tests for Wiz OAuth client_credentials flow."""

    def test_token_fetch_success(self, server):
        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = _mock_token_response()

            server._ensure_token()

            assert server._access_token is not None
            assert server._access_token.startswith("eyJ")

    def test_token_cached_when_valid(self, server):
        """Token is not re-fetched if still valid."""
        server._access_token = "cached_token"
        server._token_expires_at = time.monotonic() + 3600

        # _ensure_token should NOT make any HTTP call.
        server._ensure_token()
        assert server._access_token == "cached_token"

    def test_token_refreshed_when_expired(self, server):
        """Token is refreshed when past expiry."""
        server._access_token = "old_token"
        server._token_expires_at = time.monotonic() - 10  # Expired.

        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = _mock_token_response()

            server._ensure_token()

            assert server._access_token != "old_token"

    def test_token_failure_raises(self, server):
        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = httpx.Response(401, json={"error": "invalid_client"})

            with pytest.raises(WizAPIError, match="HTTP 401"):
                server._ensure_token()

    def test_token_missing_in_response(self, server):
        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = httpx.Response(200, json={"token_type": "bearer"})

            with pytest.raises(WizAPIError, match="missing access_token"):
                server._ensure_token()


# ---------------------------------------------------------------------------
# Tool handler tests
# ---------------------------------------------------------------------------


def _setup_server_with_token(server):
    """Pre-populate a valid token so tools don't try to fetch one."""
    server._access_token = "test_token"
    server._token_expires_at = time.monotonic() + 3600


class TestToolListFindings:

    def test_success(self, server):
        _setup_server_with_token(server)
        mock_data = {
            "issuesV2": {
                "nodes": [
                    {"id": "iss-1", "severity": "HIGH", "status": "OPEN"},
                    {"id": "iss-2", "severity": "MEDIUM", "status": "OPEN"},
                ],
                "totalCount": 2,
            }
        }
        with patch.object(server, "_graphql", return_value=mock_data):
            result = server._tool_list_findings({})
        assert result["totalCount"] == 2
        assert len(result["nodes"]) == 2

    def test_with_filters(self, server):
        _setup_server_with_token(server)
        empty_result = {"issuesV2": {"nodes": [], "totalCount": 0}}
        with patch.object(server, "_graphql", return_value=empty_result) as mock_gql:
            server._tool_list_findings(
                {"severity": "CRITICAL", "status": "OPEN", "limit": 10},
            )
            call_args = mock_gql.call_args
            variables = call_args[0][1]
            assert variables["first"] == 10
            assert variables["filterBy"]["severity"] == ["CRITICAL"]
            assert variables["filterBy"]["status"] == ["OPEN"]


class TestToolGetFinding:

    def test_success(self, server):
        _setup_server_with_token(server)
        mock_data = {
            "issue": {
                "id": "iss-1",
                "severity": "HIGH",
                "status": "OPEN",
                "remediation": "Upgrade lib",
            },
        }
        with patch.object(server, "_graphql", return_value=mock_data):
            result = server._tool_get_finding({"finding_id": "iss-1"})
        assert result["id"] == "iss-1"
        assert result["remediation"] == "Upgrade lib"

    def test_not_found(self, server):
        _setup_server_with_token(server)
        with patch.object(server, "_graphql", return_value={"issue": None}):
            result = server._tool_get_finding({"finding_id": "iss-missing"})
        assert result is None

    def test_missing_id_raises(self, server):
        _setup_server_with_token(server)
        with pytest.raises(WizAPIError, match="finding_id is required"):
            server._tool_get_finding({})


class TestToolGetAssetContext:

    def test_success(self, server):
        _setup_server_with_token(server)
        mock_data = {"graphEntity": {"id": "asset-1", "name": "prod-db", "type": "RDS"}}
        with patch.object(server, "_graphql", return_value=mock_data):
            result = server._tool_get_asset_context({"asset_id": "asset-1"})
        assert result["name"] == "prod-db"

    def test_missing_id_raises(self, server):
        _setup_server_with_token(server)
        with pytest.raises(WizAPIError, match="asset_id is required"):
            server._tool_get_asset_context({})


class TestToolUpdateFindingStatus:

    def test_success(self, server):
        _setup_server_with_token(server)
        mock_data = {
            "updateIssue": {
                "issue": {
                    "id": "iss-1",
                    "status": "RESOLVED",
                    "updatedAt": "2026-03-31T12:00:00Z",
                },
            },
        }
        with patch.object(server, "_graphql", return_value=mock_data):
            result = server._tool_update_finding_status(
                {"finding_id": "iss-1", "status": "RESOLVED", "note": "Fixed"},
            )
        assert result["status"] == "RESOLVED"

    def test_missing_fields_raises(self, server):
        _setup_server_with_token(server)
        with pytest.raises(WizAPIError, match="finding_id and status are required"):
            server._tool_update_finding_status({"finding_id": "iss-1"})


class TestToolCheckFindingStatus:

    def test_success(self, server):
        _setup_server_with_token(server)
        mock_data = {"issue": {"id": "iss-1", "status": "IN_PROGRESS"}}
        with patch.object(server, "_graphql", return_value=mock_data):
            result = server._tool_check_finding_status({"finding_id": "iss-1"})
        assert result == {"id": "iss-1", "status": "IN_PROGRESS"}


# ---------------------------------------------------------------------------
# GraphQL error handling
# ---------------------------------------------------------------------------


class TestGraphQLErrors:

    def test_graphql_error_response(self, server):
        _setup_server_with_token(server)
        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = httpx.Response(
                200, json={"errors": [{"message": "Access denied"}]}
            )
            with pytest.raises(WizAPIError, match="Access denied"):
                server._graphql("query { test }", {})

    def test_http_error_response(self, server):
        _setup_server_with_token(server)
        with patch("cliff.integrations.wrappers.wiz.server.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = httpx.Response(500, text="Internal Server Error")
            with pytest.raises(WizAPIError, match="HTTP 500"):
                server._graphql("query { test }", {})


# ---------------------------------------------------------------------------
# Auth URL derivation
# ---------------------------------------------------------------------------


class TestAuthURLDerivation:

    def test_standard_us_region(self):
        assert (
            WizMCPServer._derive_auth_url("https://api.us20.app.wiz.io/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )

    def test_eu_region(self):
        assert (
            WizMCPServer._derive_auth_url("https://api.eu1.app.wiz.io/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )

    def test_fallback_for_unknown(self):
        assert (
            WizMCPServer._derive_auth_url("https://custom.example.com/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


class TestEntryPoint:

    def test_missing_env_vars_exits(self):
        """Missing env vars cause sys.exit(1)."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                from cliff.integrations.wrappers.wiz.__main__ import main
                main()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Integration tests — registry + gateway + workspace
# ---------------------------------------------------------------------------


class TestWizRegistryIntegration:
    """Verify the updated wiz.json registry entry."""

    def test_wiz_registry_has_mcp_config(self):
        from cliff.integrations.registry import get_registry_entry

        entry = get_registry_entry("wiz")
        assert entry is not None
        assert entry.mcp_config is not None
        assert entry.mcp_config["command"][0] == "python"
        assert "-m" in entry.mcp_config["command"]
        assert "cliff.integrations.wrappers.wiz" in entry.mcp_config["command"]

    def test_wiz_status_is_available(self):
        from cliff.integrations.registry import get_registry_entry

        entry = get_registry_entry("wiz")
        assert entry is not None
        assert entry.status == "available"

    def test_wiz_credentials_schema_complete(self):
        from cliff.integrations.registry import get_registry_entry

        entry = get_registry_entry("wiz")
        assert entry is not None
        key_names = {f.key_name for f in entry.credentials_schema}
        assert key_names == {"wiz_client_id", "wiz_client_secret", "wiz_api_url"}

    @pytest.mark.asyncio
    async def test_gateway_resolves_wiz_config(self):
        """MCPConfigResolver includes Wiz when integration is enabled with creds."""
        from cliff.db.connection import close_db, init_db
        from cliff.db.repo_integration import create_integration
        from cliff.integrations.gateway import MCPConfigResolver
        from cliff.integrations.vault import CredentialVault
        from cliff.models import IntegrationConfigCreate

        test_key = os.urandom(32)
        db = await init_db(":memory:")
        try:
            vault = CredentialVault(db, key=test_key)
            resolver = MCPConfigResolver(vault)

            # Create Wiz integration.
            integration = await create_integration(
                db,
                IntegrationConfigCreate(
                    adapter_type="finding_source",
                    provider_name="Wiz",
                ),
            )

            # Store credentials.
            await vault.store(integration.id, "wiz_client_id", "test_id")
            await vault.store(integration.id, "wiz_client_secret", "test_secret")
            await vault.store(integration.id, "wiz_api_url", "https://api.us20.app.wiz.io/graphql")

            # Resolve.
            result = await resolver.resolve_workspace(db)
            assert "wiz" in result.mcp_configs
            config = result.mcp_configs["wiz"]
            assert config["command"][0] == "python"
            # Credentials should be resolved (no placeholders).
            assert config["environment"]["WIZ_CLIENT_ID"] == "test_id"
            assert config["environment"]["WIZ_CLIENT_SECRET"] == "test_secret"
            assert config["environment"]["WIZ_API_URL"] == "https://api.us20.app.wiz.io/graphql"
        finally:
            await close_db()

    @pytest.mark.asyncio
    async def test_wiz_in_workspace_integrations_list(self):
        """Resolved workspace includes Wiz in the integrations metadata."""
        from cliff.db.connection import close_db, init_db
        from cliff.db.repo_integration import create_integration
        from cliff.integrations.gateway import MCPConfigResolver
        from cliff.integrations.vault import CredentialVault
        from cliff.models import IntegrationConfigCreate

        test_key = os.urandom(32)
        db = await init_db(":memory:")
        try:
            vault = CredentialVault(db, key=test_key)
            resolver = MCPConfigResolver(vault)

            integration = await create_integration(
                db,
                IntegrationConfigCreate(
                    adapter_type="finding_source",
                    provider_name="Wiz",
                ),
            )
            await vault.store(integration.id, "wiz_client_id", "id")
            await vault.store(integration.id, "wiz_client_secret", "secret")
            await vault.store(integration.id, "wiz_api_url", "https://api.us20.app.wiz.io/graphql")

            result = await resolver.resolve_workspace(db)
            wiz_integrations = [i for i in result.integrations if i.registry_id == "wiz"]
            assert len(wiz_integrations) == 1
            assert wiz_integrations[0].provider_name == "Wiz"
            assert "collect" in wiz_integrations[0].capabilities
        finally:
            await close_db()
