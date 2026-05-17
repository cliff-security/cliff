"""Tests for the GitHub App **manual setup recovery** endpoint (B33, IMPL-0016).

The shared GitHub App's Setup URL is registered globally on github.com and
is hardcoded to ``http://localhost:8000/api/integrations/github/setup`` — it
can't vary per installation or per deployment. Any Cliff instance bound to
a different host port (Docker remap, parallel dev stack, reverse proxy)
never receives the post-install ``GET /setup`` callback.

``POST /api/integrations/github/setup/manual`` lets a user recover by
pasting the ``installation_id`` they saw in the GitHub redirect URL. The
endpoint reuses the same registration code path as the GET callback —
critically including CSRF state validation, so a pasted ``installation_id``
that wasn't bound to a state we issued is rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cliff.integrations.github_app.client import (
    DeviceCodeResponse,
    PollTokenResult,
    UserInfo,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Fakes / fixtures (mirrors test_github_app_routes.py — kept in sync but
# scoped to this file so the manual-recovery tests don't depend on the
# layout of the existing setup tests)
# ---------------------------------------------------------------------------


class FakeClient:
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

    async def request_device_code(self) -> DeviceCodeResponse:
        return self.device_code_response

    async def poll_token(self, *, device_code: str) -> PollTokenResult:  # noqa: ARG002
        return self.poll_result

    async def fetch_user(self, *, access_token: str) -> UserInfo:  # noqa: ARG002
        return self.user_info


@pytest.fixture
def fake_github_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
async def app_state(db_client):  # noqa: ARG001 — orders init after db_client
    from cliff.db import connection as db_connection
    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.vault import CredentialVault
    from cliff.main import app

    db = db_connection._db
    assert db is not None
    vault = CredentialVault(db, key=b"\x00" * 32)
    audit = AuditLogger(db)
    await audit.start()
    app.state.vault = vault
    app.state.audit_logger = audit
    app.state.github_app_orchestrator = None
    yield
    await audit.stop()
    app.state.vault = None
    app.state.audit_logger = None
    app.state.github_app_orchestrator = None


@pytest.fixture
def patched_app_settings(app_state):  # noqa: ARG001
    from cliff.config import settings

    with (
        patch.object(settings, "github_app_client_id", "Iv23liTestClient"),
        patch.object(settings, "github_app_slug", "opensec"),
        patch.object(settings, "base_url", "http://localhost:8000"),
    ):
        yield


@pytest.fixture
def patched_client_factory(fake_github_client: FakeClient):
    from cliff.api.routes import github_app as routes_module

    with patch.object(
        routes_module,
        "_build_github_client",
        return_value=fake_github_client,
    ):
        yield fake_github_client


# ---------------------------------------------------------------------------
# /setup/manual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_setup_registers_install_with_valid_state(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """POST /setup/manual with a valid (issued-by-/connect) state binds the
    installation_id the same way GET /setup would, advancing the row out
    of ``installation_pending``."""
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 12345, "state": csrf_state},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["installation_id"] == 12345
    # Status flips off installation_pending; device_pending is the
    # post-install/pre-authorize stage.
    assert body["status"] in {"device_pending", "connected"}

    # The /status route confirms the install was registered against the
    # right integration row.
    status_resp = await db_client.get("/api/integrations/github/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["installation_id"] == 12345


@pytest.mark.asyncio
async def test_manual_setup_rejects_invalid_state(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """The pasted state MUST match a state /connect issued. An attacker who
    tricks the user into pasting an attacker-controlled installation_id
    would otherwise bind a fake install to the user's account."""
    # No /connect call yet → no valid state has been issued.
    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 12345, "state": "not-a-real-csrf-token"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "csrf" in detail or "state" in detail


@pytest.mark.asyncio
async def test_manual_setup_rejects_state_from_different_flow(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """Even a well-formed-but-wrong state must be rejected — only states
    that were issued by the current process's /connect are valid."""
    # Kick off a /connect to make sure the in-memory return-path map is
    # populated for at least one state; the manual POST then submits a
    # *different* state that no /connect ever issued.
    await db_client.post("/api/integrations/github/connect")

    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 99999, "state": "x" * 32},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_manual_setup_idempotent(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """Re-POSTing the same (state, installation_id) pair must NOT create
    a duplicate row or fail — operators commonly retry under uncertainty."""
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    first = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 88, "state": csrf_state},
    )
    assert first.status_code == 200

    second = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 88, "state": csrf_state},
    )
    assert second.status_code == 200
    assert second.json()["installation_id"] == 88


@pytest.mark.asyncio
async def test_manual_setup_rejects_replay_with_different_installation_id(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """SR-2 (manual): once a state has been bound to one installation_id,
    a replay with a *different* installation_id must be rejected — same
    guarantee the GET callback provides."""
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    first = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 1234, "state": csrf_state},
    )
    assert first.status_code == 200

    replay = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 9999, "state": csrf_state},
    )
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_manual_setup_rejects_zero_or_negative_installation_id(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """GitHub installation IDs are always positive integers — reject the
    nonsense early before consulting the DB."""
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 0, "state": csrf_state},
    )
    assert resp.status_code == 422

    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": -5, "state": csrf_state},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_manual_setup_rejects_cross_origin_request(
    db_client: AsyncClient,
    patched_app_settings,  # noqa: ARG001
    patched_client_factory,  # noqa: ARG001
):
    """Same-origin guard applies — a malicious page on another origin
    can't trigger a recovery POST against the user's own Cliff."""
    connect_resp = await db_client.post("/api/integrations/github/connect")
    csrf_state = connect_resp.json()["install_url"].rsplit("state=", 1)[1]

    resp = await db_client.post(
        "/api/integrations/github/setup/manual",
        json={"installation_id": 12345, "state": csrf_state},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manual_setup_returns_503_when_app_unconfigured(
    db_client: AsyncClient,
    app_state,  # noqa: ARG001
):
    """If the operator never set OPENSEC_GITHUB_APP_CLIENT_ID, the manual
    recovery path should mirror the rest of the GitHub routes and 503."""
    from cliff.config import settings

    with (
        patch.object(settings, "github_app_client_id", ""),
        patch.object(settings, "github_app_slug", ""),
    ):
        resp = await db_client.post(
            "/api/integrations/github/setup/manual",
            json={"installation_id": 12345, "state": "anything"},
        )
        assert resp.status_code == 503
