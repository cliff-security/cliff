"""Tests for the github_app API routes (IMPL-0010, Phase 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from opensec.integrations.github_app.client import (
    DeviceCodeResponse,
    PollTokenResult,
    UserInfo,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Fake GithubAppClient honoring the protocol used by the orchestrator."""

    def __init__(self) -> None:
        self.device_code_response = DeviceCodeResponse(
            device_code="DEV-CODE-1",
            user_code="MNPQ-RSTU",
            verification_uri="https://github.com/login/device",
            expires_in=900,
            interval=5,
        )
        self.poll_result = PollTokenResult(kind="authorization_pending")
        self.user_info = UserInfo(login="octocat", id=1)
        self.poll_calls = 0

    async def request_device_code(self) -> DeviceCodeResponse:
        return self.device_code_response

    async def poll_token(self, *, device_code: str) -> PollTokenResult:  # noqa: ARG002
        self.poll_calls += 1
        return self.poll_result

    async def fetch_user(self, *, access_token: str) -> UserInfo:  # noqa: ARG002
        return self.user_info


@pytest.fixture
def fake_github_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
async def app_state(db_client):  # noqa: ARG001 — depends on db_client to ensure init order
    """Wire up vault + audit logger on app.state for the github_app routes."""
    from opensec.db import connection as db_connection
    from opensec.integrations.audit import AuditLogger
    from opensec.integrations.vault import CredentialVault
    from opensec.main import app

    db = db_connection._db
    assert db is not None
    vault = CredentialVault(db, key=b"\x00" * 32)
    audit = AuditLogger(db)
    await audit.start()
    app.state.vault = vault
    app.state.audit_logger = audit
    yield
    await audit.stop()
    app.state.vault = None
    app.state.audit_logger = None


@pytest.fixture
def patched_app_settings(app_state):  # noqa: ARG001
    """Force the github_app feature flag ON via env override and ensure
    OPENSEC_BASE_URL points at the default hard-coded localhost. Depends
    on app_state so vault + audit logger are also wired up."""
    from opensec.config import settings

    with (
        patch.object(settings, "github_app_client_id", "Iv23liTestClient"),
        patch.object(settings, "github_app_slug", "opensec"),
        patch.object(settings, "base_url", "http://localhost:8000"),
    ):
        yield


@pytest.fixture
def patched_disabled_app_settings(app_state):  # noqa: ARG001
    """Simulate the App being unconfigured (env var unset)."""
    from opensec.config import settings

    with (
        patch.object(settings, "github_app_client_id", ""),
        patch.object(settings, "github_app_slug", ""),
    ):
        yield


@pytest.fixture
def patched_client_factory(fake_github_client: FakeClient):
    """Replace the orchestrator's client factory so it never hits the real
    network. Patches the helper that the routes module uses to construct
    its orchestrator."""
    from opensec.api.routes import github_app as routes_module

    with patch.object(
        routes_module,
        "_build_github_client",
        return_value=fake_github_client,
    ):
        yield fake_github_client


# ---------------------------------------------------------------------------
# /connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_returns_503_when_client_id_unset(
    db_client: AsyncClient,
    patched_disabled_app_settings,  # noqa: ARG001
):
    resp = await db_client.post("/api/integrations/github/connect")
    assert resp.status_code == 503
    assert "github app" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_connect_returns_user_code_and_install_url(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    resp = await db_client.post("/api/integrations/github/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_code"] == "MNPQ-RSTU"
    assert body["verification_uri"] == "https://github.com/login/device"
    assert body["interval"] == 5
    assert body["install_url"].startswith(
        "https://github.com/apps/opensec/installations/new?state="
    )


@pytest.mark.asyncio
async def test_connect_idempotent_for_existing_inflight(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    first = await db_client.post("/api/integrations/github/connect")
    second = await db_client.post("/api/integrations/github/connect")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user_code"] == second.json()["user_code"]
    assert first.json()["install_url"] == second.json()["install_url"]


# ---------------------------------------------------------------------------
# /setup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_validates_csrf_and_redirects_with_complete_flag(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    connect_resp = await db_client.post("/api/integrations/github/connect")
    install_url = connect_resp.json()["install_url"]
    csrf_state = install_url.rsplit("state=", 1)[1]

    resp = await db_client.get(
        "/api/integrations/github/setup",
        params={
            "installation_id": "987654",
            "setup_action": "install",
            "state": csrf_state,
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 307}
    location = resp.headers["location"]
    assert "/settings/integrations" in location
    assert "github_setup=complete" in location


@pytest.mark.asyncio
async def test_setup_redirects_with_error_on_csrf_mismatch(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    resp = await db_client.get(
        "/api/integrations/github/setup",
        params={
            "installation_id": "111",
            "setup_action": "install",
            "state": "definitely-not-a-real-csrf-token",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 307}
    location = resp.headers["location"]
    assert "github_setup=error" in location


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_404_when_no_inflight(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
):
    resp = await db_client.get("/api/integrations/github/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_reports_pending_after_connect(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    await db_client.post("/api/integrations/github/connect")
    resp = await db_client.get("/api/integrations/github/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"installation_pending", "device_pending"}
    assert body["user_code"] == "MNPQ-RSTU"


@pytest.mark.asyncio
async def test_status_reports_connected_after_successful_poll(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
    fake_github_client: FakeClient,
):
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    # Simulate the install callback then a successful authorize.
    await db_client.get(
        "/api/integrations/github/setup",
        params={
            "installation_id": "55",
            "setup_action": "install",
            "state": csrf_state,
        },
        follow_redirects=False,
    )
    fake_github_client.poll_result = PollTokenResult(
        kind="success", access_token="ghu_test"
    )

    # Drive a single polling step via the public test seam.
    from opensec.api.routes import github_app as routes_module

    await routes_module._tick_poll_for_test()

    resp = await db_client.get("/api/integrations/github/status")
    body = resp.json()
    assert body["status"] == "connected"
    assert body["github_login"] == "octocat"
    assert body["installation_id"] == 55


# ---------------------------------------------------------------------------
# /disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_returns_manual_revoke_url(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    await db_client.post("/api/integrations/github/connect")
    resp = await db_client.post("/api/integrations/github/disconnect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "disconnected"
    assert body["manual_revoke_url"] == "https://github.com/settings/applications"


@pytest.mark.asyncio
async def test_disconnect_is_safe_when_nothing_connected(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
):
    resp = await db_client.post("/api/integrations/github/disconnect")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Registry availability flag (settings route enrichment)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_marks_github_app_available_when_client_id_set(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
):
    resp = await db_client.get("/api/settings/integrations/registry")
    assert resp.status_code == 200
    entries = {e["id"]: e for e in resp.json()}
    assert entries["github"]["github_app_available"] is True


@pytest.mark.asyncio
async def test_registry_marks_github_app_unavailable_when_client_id_unset(
    db_client: AsyncClient,
    patched_disabled_app_settings,  # noqa: ARG001
):
    resp = await db_client.get("/api/settings/integrations/registry")
    assert resp.status_code == 200
    entries = {e["id"]: e for e in resp.json()}
    assert entries["github"]["github_app_available"] is False
