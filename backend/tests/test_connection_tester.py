"""Tests for the connection testing framework (Phase I-2).

All tests mock HTTP responses via ``pytest-httpx`` — no real external calls.
"""

from __future__ import annotations

import httpx
import pytest

from cliff.integrations.connection_tester import (
    GitHubConnectionTester,
    JiraCloudConnectionTester,
    WizConnectionTester,
    get_tester,
    run_connection_test,
)

# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class TestGitHubConnectionTester:
    """Tests for GitHubConnectionTester."""

    @pytest.fixture
    def tester(self):
        return GitHubConnectionTester()

    @pytest.fixture
    def creds(self):
        return {"github_personal_access_token": "ghp_test_token_123"}

    @pytest.mark.asyncio
    async def test_success(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "octocat"},
            headers={"x-oauth-scopes": "repo, read:org"},
        )
        result = await tester.test(creds)
        assert result.success is True
        assert "octocat" in result.message
        assert result.details["username"] == "octocat"
        assert result.details["scopes"] == "repo, read:org"

    @pytest.mark.asyncio
    async def test_invalid_token(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://api.github.com/user",
            status_code=401,
            json={"message": "Bad credentials"},
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "Invalid or expired" in result.message

    @pytest.mark.asyncio
    async def test_insufficient_scopes(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://api.github.com/user",
            status_code=403,
            json={"message": "Forbidden"},
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "lacks required permissions" in result.message

    @pytest.mark.asyncio
    async def test_timeout(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        result = await tester.test(creds)
        assert result.success is False
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_network_error(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        result = await tester.test(creds)
        assert result.success is False
        assert "Could not connect" in result.message

    @pytest.mark.asyncio
    async def test_missing_credentials(self, tester):
        result = await tester.test({})
        assert result.success is False
        assert "Missing credential" in result.message


# ---------------------------------------------------------------------------
# Jira Cloud
# ---------------------------------------------------------------------------


class TestJiraCloudConnectionTester:
    """Tests for JiraCloudConnectionTester."""

    @pytest.fixture
    def tester(self):
        return JiraCloudConnectionTester()

    @pytest.fixture
    def creds(self):
        return {
            "jira_url": "https://mycompany.atlassian.net",
            "jira_email": "user@company.com",
            "jira_api_token": "ATATT3xtest",
        }

    @pytest.mark.asyncio
    async def test_success(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://mycompany.atlassian.net/rest/api/3/myself",
            json={"displayName": "Jane Doe", "emailAddress": "user@company.com"},
        )
        result = await tester.test(creds)
        assert result.success is True
        assert "Jane Doe" in result.message
        assert result.details["display_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_invalid_credentials(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://mycompany.atlassian.net/rest/api/3/myself",
            status_code=401,
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "Invalid Jira credentials" in result.message

    @pytest.mark.asyncio
    async def test_bad_url(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        result = await tester.test(creds)
        assert result.success is False
        assert "Could not connect" in result.message

    @pytest.mark.asyncio
    async def test_timeout(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        result = await tester.test(creds)
        assert result.success is False
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self, tester):
        result = await tester.test({"jira_url": "https://x.atlassian.net"})
        assert result.success is False
        assert "jira_email" in result.message
        assert "jira_api_token" in result.message

    @pytest.mark.asyncio
    async def test_not_found(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://mycompany.atlassian.net/rest/api/3/myself",
            status_code=404,
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "not found" in result.message.lower()


# ---------------------------------------------------------------------------
# Wiz
# ---------------------------------------------------------------------------


class TestWizConnectionTester:
    """Tests for WizConnectionTester."""

    @pytest.fixture
    def tester(self):
        return WizConnectionTester()

    @pytest.fixture
    def creds(self):
        return {
            "wiz_client_id": "wiz_sa_test",
            "wiz_client_secret": "secret_value",
            "wiz_api_url": "https://api.us20.app.wiz.io/graphql",
        }

    @pytest.mark.asyncio
    async def test_success(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.app.wiz.io/oauth/token",
            json={"access_token": "eyJhbGc...", "token_type": "bearer", "expires_in": 86400},
        )
        result = await tester.test(creds)
        assert result.success is True
        assert "successful" in result.message.lower()
        assert result.details["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_invalid_client(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.app.wiz.io/oauth/token",
            status_code=401,
            json={"error": "invalid_client"},
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "Invalid Wiz client credentials" in result.message

    @pytest.mark.asyncio
    async def test_timeout(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        result = await tester.test(creds)
        assert result.success is False
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_malformed_response(self, tester, creds, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.app.wiz.io/oauth/token",
            json={"token_type": "bearer"},  # Missing access_token
        )
        result = await tester.test(creds)
        assert result.success is False
        assert "no access token" in result.message.lower()

    @pytest.mark.asyncio
    async def test_network_error(self, tester, creds, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        result = await tester.test(creds)
        assert result.success is False
        assert "Could not connect" in result.message

    @pytest.mark.asyncio
    async def test_missing_credentials(self, tester):
        result = await tester.test({"wiz_client_id": "x"})
        assert result.success is False
        assert "wiz_client_secret" in result.message
        assert "wiz_api_url" in result.message

    @pytest.mark.asyncio
    async def test_auth_url_derivation(self, tester):
        """Verify auth URL is derived correctly from different API URLs."""
        assert (
            tester._derive_auth_url("https://api.us20.app.wiz.io/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )
        assert (
            tester._derive_auth_url("https://api.eu1.app.wiz.io/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )
        # Fallback for unexpected format.
        assert (
            tester._derive_auth_url("https://custom.wiz.example.com/graphql")
            == "https://auth.app.wiz.io/oauth/token"
        )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    """Tests for the dispatch registry and run_connection_test function."""

    def test_get_tester_github(self):
        tester = get_tester("github")
        assert isinstance(tester, GitHubConnectionTester)

    def test_get_tester_jira(self):
        tester = get_tester("jira-cloud")
        assert isinstance(tester, JiraCloudConnectionTester)

    def test_get_tester_wiz(self):
        tester = get_tester("wiz")
        assert isinstance(tester, WizConnectionTester)

    def test_get_tester_unknown(self):
        assert get_tester("unknown-provider") is None

    @pytest.mark.asyncio
    async def test_run_connection_test_returns_none_for_unknown(self):
        result = await run_connection_test("snyk", {"snyk_api_token": "x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_run_connection_test_dispatches_github(self, httpx_mock):
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "testuser"},
            headers={"x-oauth-scopes": "repo"},
        )
        result = await run_connection_test(
            "github", {"github_personal_access_token": "ghp_test"}
        )
        assert result is not None
        assert result.success is True
        assert "testuser" in result.message


# ---------------------------------------------------------------------------
# API-level test — test_connection endpoint with real tester dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_dispatches_real_tester(httpx_mock):
    """The /settings/integrations/{id}/test endpoint dispatches to real testers."""
    import os
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.db.connection import close_db, init_db
    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault
    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    db = await init_db(":memory:")

    test_key = os.urandom(32)
    app.state.vault = CredentialVault(db, key=test_key)
    audit_logger = AuditLogger(db)
    await audit_logger.start()
    app.state.audit_logger = audit_logger

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a GitHub integration.
        resp = await ac.post(
            "/api/settings/integrations",
            json={"adapter_type": "finding_source", "provider_name": "GitHub"},
        )
        assert resp.status_code == 201
        iid = resp.json()["id"]

        # Store the credential.
        resp2 = await ac.post(
            f"/api/settings/integrations/{iid}/credentials",
            json={"key_name": "github_personal_access_token", "value": "ghp_test123"},
        )
        assert resp2.status_code == 201

        # Mock the GitHub API response.
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "octocat"},
            headers={"x-oauth-scopes": "repo"},
        )

        # Test connection — should dispatch to GitHubConnectionTester.
        resp3 = await ac.post(f"/api/settings/integrations/{iid}/test")
        assert resp3.status_code == 200
        data = resp3.json()
        assert data["success"] is True
        assert "octocat" in data["message"]

    await audit_logger.stop()
    await close_db()


@pytest.mark.asyncio
async def test_endpoint_fallback_for_unknown_provider(httpx_mock):
    """Unknown providers fall back to credential-decrypted check."""
    import os
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    from cliff.db.connection import close_db, init_db
    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault
    from cliff.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    app.router.lifespan_context = _noop_lifespan
    db = await init_db(":memory:")

    test_key = os.urandom(32)
    app.state.vault = CredentialVault(db, key=test_key)
    audit_logger = AuditLogger(db)
    await audit_logger.start()
    app.state.audit_logger = audit_logger

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a Snyk integration (no tester registered).
        resp = await ac.post(
            "/api/settings/integrations",
            json={"adapter_type": "finding_source", "provider_name": "Snyk"},
        )
        assert resp.status_code == 201
        iid = resp.json()["id"]

        # Store a credential.
        resp2 = await ac.post(
            f"/api/settings/integrations/{iid}/credentials",
            json={"key_name": "snyk_api_token", "value": "tok_test"},
        )
        assert resp2.status_code == 201

        # Test connection — should fall back to "credentials decrypted".
        resp3 = await ac.post(f"/api/settings/integrations/{iid}/test")
        assert resp3.status_code == 200
        data = resp3.json()
        assert data["success"] is True
        assert "decrypted" in data["message"].lower()

    await audit_logger.stop()
    await close_db()
