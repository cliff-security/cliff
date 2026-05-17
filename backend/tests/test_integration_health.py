"""Tests for integration health monitoring (Phase I-2, PR4).

Verifies credential status checks, connection tester dispatch, audit logging,
and the API endpoints.
"""

from __future__ import annotations

import os

import pytest

from cliff.integrations.health import IntegrationHealthMonitor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_KEY = os.urandom(32)


@pytest.fixture
async def db():
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def vault(db):
    from cliff.integrations.vault import CredentialVault

    return CredentialVault(db, key=TEST_KEY)


@pytest.fixture
async def audit(db):
    from cliff.integrations.audit import AuditLogger

    logger = AuditLogger(db)
    await logger.start()
    yield logger
    await logger.stop()


@pytest.fixture
def monitor(vault, audit):
    return IntegrationHealthMonitor(vault, audit_logger=audit)


async def _create_github_integration(db, vault):
    """Helper: create GitHub integration with valid credentials."""
    from cliff.db.repo_integration import create_integration
    from cliff.models import IntegrationConfigCreate

    integration = await create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="GitHub",
        ),
    )
    await vault.store(
        integration.id, "github_personal_access_token", "ghp_health_test"
    )
    return integration


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


class TestHealthCheck:

    @pytest.mark.asyncio
    async def test_success(self, db, vault, monitor, httpx_mock):
        integration = await _create_github_integration(db, vault)
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "healthbot"},
            headers={"x-oauth-scopes": "repo"},
        )
        health = await monitor.check_health(db, integration.id)
        assert health is not None
        assert health.credential_status == "ok"
        assert health.connection_status == "ok"
        assert health.error_message is None

    @pytest.mark.asyncio
    async def test_not_found(self, db, monitor):
        health = await monitor.check_health(db, "nonexistent-id")
        assert health is None

    @pytest.mark.asyncio
    async def test_missing_credentials(self, db, monitor):
        from cliff.db.repo_integration import create_integration
        from cliff.models import IntegrationConfigCreate

        integration = await create_integration(
            db,
            IntegrationConfigCreate(
                adapter_type="finding_source",
                provider_name="GitHub",
            ),
        )
        health = await monitor.check_health(db, integration.id)
        assert health.credential_status == "missing"
        assert health.connection_status == "unchecked"

    @pytest.mark.asyncio
    async def test_connection_failure(self, db, vault, monitor, httpx_mock):
        integration = await _create_github_integration(db, vault)
        httpx_mock.add_response(
            url="https://api.github.com/user",
            status_code=401,
            json={"message": "Bad credentials"},
        )
        health = await monitor.check_health(db, integration.id)
        assert health.credential_status == "ok"
        assert health.connection_status == "error"
        assert health.error_message is not None

    @pytest.mark.asyncio
    async def test_unknown_provider_unchecked(self, db, vault, monitor):
        """Provider without a tester gets connection_status='unchecked'."""
        from cliff.db.repo_integration import create_integration
        from cliff.models import IntegrationConfigCreate

        integration = await create_integration(
            db,
            IntegrationConfigCreate(
                adapter_type="finding_source",
                provider_name="Snyk",
            ),
        )
        await vault.store(integration.id, "snyk_api_token", "tok")
        health = await monitor.check_health(db, integration.id)
        assert health.credential_status == "ok"
        assert health.connection_status == "unchecked"

    @pytest.mark.asyncio
    async def test_audit_logged(self, db, vault, monitor, httpx_mock):
        from cliff.db.repo_audit import query_audit_log

        integration = await _create_github_integration(db, vault)
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "auditbot"},
            headers={"x-oauth-scopes": ""},
        )
        await monitor.check_health(db, integration.id)

        # Flush audit queue.
        await monitor._audit.stop()
        events = await query_audit_log(
            db, event_type="integration.health_check"
        )
        assert len(events) >= 1
        assert events[0]["status"] == "success"


class TestCheckAll:

    @pytest.mark.asyncio
    async def test_check_all(self, db, vault, monitor, httpx_mock):
        from cliff.db.repo_integration import create_integration
        from cliff.models import IntegrationConfigCreate

        # Two integrations: GitHub + Snyk.
        await _create_github_integration(db, vault)
        snyk = await create_integration(
            db,
            IntegrationConfigCreate(
                adapter_type="finding_source",
                provider_name="Snyk",
            ),
        )
        await vault.store(snyk.id, "snyk_api_token", "tok")

        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "allbot"},
            headers={"x-oauth-scopes": ""},
        )

        results = await monitor.check_all(db)
        assert len(results) == 2
        gh_health = next(r for r in results if r.registry_id == "github")
        snyk_health = next(r for r in results if r.registry_id == "snyk")
        assert gh_health.connection_status == "ok"
        assert snyk_health.connection_status == "unchecked"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_single(httpx_mock):
    """GET /settings/integrations/{id}/health returns health status."""
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

    app.state.vault = CredentialVault(db, key=os.urandom(32))
    audit_logger = AuditLogger(db)
    await audit_logger.start()
    app.state.audit_logger = audit_logger

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create integration + credential.
        resp = await ac.post(
            "/api/settings/integrations",
            json={"adapter_type": "finding_source", "provider_name": "GitHub"},
        )
        iid = resp.json()["id"]
        await ac.post(
            f"/api/settings/integrations/{iid}/credentials",
            json={
                "key_name": "github_personal_access_token",
                "value": "ghp_api_health",
            },
        )

        # Mock GitHub API.
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "apibot"},
            headers={"x-oauth-scopes": "repo"},
        )

        resp2 = await ac.get(f"/api/settings/integrations/{iid}/health")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["credential_status"] == "ok"
        assert data["connection_status"] == "ok"

    await audit_logger.stop()
    await close_db()
