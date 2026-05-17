"""Tests for token refresh + 401-retry hook (IMPL-0010, Phase 5)."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import httpx
import pytest

from cliff.assessment.posture.github_client import GithubClient, UnableToVerify
from cliff.db import repo_integration
from cliff.db.connection import close_db, init_db
from cliff.integrations.audit import AuditLogger
from cliff.integrations.github_app import repo as gh_repo
from cliff.integrations.github_app.client import (
    DeviceCodeResponse,
    PollTokenResult,
    UserInfo,
)
from cliff.integrations.github_app.flow import (
    refresh_user_access_token,
)
from cliff.integrations.github_app.models import GithubAppInstallationCreate
from cliff.integrations.vault import CredentialVault
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite


VAULT_KEY = b"\x00" * 32
GITHUB_TOKEN_KEY = "github_personal_access_token"
GITHUB_REFRESH_KEY = "github_refresh_token"  # noqa: S105 — vault key name, not a credential


# ---------------------------------------------------------------------------
# refresh_user_access_token helper
# ---------------------------------------------------------------------------


class _FakeRefreshClient:
    def __init__(self, result: PollTokenResult) -> None:
        self._result = result

    async def refresh_access_token(self, *, refresh_token: str) -> PollTokenResult:  # noqa: ARG002
        return self._result

    # Stubs for protocol
    async def request_device_code(self) -> DeviceCodeResponse:  # pragma: no cover
        raise NotImplementedError

    async def poll_token(self, *, device_code: str) -> PollTokenResult:  # pragma: no cover
        raise NotImplementedError

    async def fetch_user(self, *, access_token: str) -> UserInfo:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def vault(db):
    return CredentialVault(db, key=VAULT_KEY)


@pytest.fixture
async def audit(db):
    a = AuditLogger(db)
    await a.start()
    yield a
    await a.stop()


@pytest.fixture
async def integration_id(db):
    integ = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="github",
            enabled=True,
            config=None,
            action_tier=0,
        ),
    )
    return integ.id


@pytest.fixture
async def connected_install(db, vault, integration_id):
    """A fully-connected GitHub App installation with a refresh token in the vault."""
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="cliff",
            client_id="cid",
            csrf_state="csrf-x",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2099-01-01T00:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )
    await gh_repo.mark_connected(
        db, integration_id, github_login="octocat", token_expires_at=None
    )
    await vault.store(integration_id, GITHUB_TOKEN_KEY, "ghu_old")
    await vault.store(integration_id, GITHUB_REFRESH_KEY, "ghr_old")
    return integration_id


@pytest.mark.asyncio
async def test_refresh_swaps_token_under_same_credential_key(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    connected_install: str,
):
    fake = _FakeRefreshClient(
        PollTokenResult(
            kind="success",
            access_token="ghu_new",
            refresh_token="ghr_new",
            expires_in=28800,
        )
    )
    new_token = await refresh_user_access_token(
        db=db,
        vault=vault,
        audit=audit,
        client=fake,
        integration_id=connected_install,
    )

    assert new_token == "ghu_new"
    assert await vault.retrieve(connected_install, GITHUB_TOKEN_KEY) == "ghu_new"
    assert await vault.retrieve(connected_install, GITHUB_REFRESH_KEY) == "ghr_new"


@pytest.mark.asyncio
async def test_refresh_failure_marks_integration_needs_reconnect(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    connected_install: str,
):
    class RaisingClient:
        async def refresh_access_token(self, *, refresh_token: str) -> PollTokenResult:  # noqa: ARG002
            raise RuntimeError("invalid_grant")

    with pytest.raises(RuntimeError):
        await refresh_user_access_token(
            db=db,
            vault=vault,
            audit=audit,
            client=RaisingClient(),  # type: ignore[arg-type]
            integration_id=connected_install,
        )

    record = await gh_repo.get_for_integration(db, connected_install)
    assert record is not None
    assert record.polling_status == "error"
    assert record.polling_error == "needs_reconnect"


@pytest.mark.asyncio
async def test_refresh_returns_none_when_no_refresh_token_stored(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    integration_id: str,
):
    # Connected, but no refresh token stored (App has expiry disabled).
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="cliff",
            client_id="cid",
            csrf_state="csrf",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2099-01-01T00:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )
    await gh_repo.mark_connected(
        db, integration_id, github_login="octocat", token_expires_at=None
    )
    await vault.store(integration_id, GITHUB_TOKEN_KEY, "ghu_only")

    fake = _FakeRefreshClient(
        PollTokenResult(kind="success", access_token="should_not_be_used")
    )
    result = await refresh_user_access_token(
        db=db,
        vault=vault,
        audit=audit,
        client=fake,  # type: ignore[arg-type]
        integration_id=integration_id,
    )
    assert result is None


# ---------------------------------------------------------------------------
# GithubClient 401-retry hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_client_retries_after_refresh_on_401():
    captured_tokens: list[str | None] = []
    statuses: deque[int] = deque([401, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        captured_tokens.append(
            request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            or None
        )
        status = statuses.popleft()
        if status == 200:
            return httpx.Response(200, json={"name": "demo-repo"})
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    refresh_calls = 0

    async def refresh_callback() -> str:
        nonlocal refresh_calls
        refresh_calls += 1
        return "ghu_fresh"

    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(
            http, token="ghu_stale", refresh_callback=refresh_callback
        )
        result = await client.get_repo_info("octo", "demo")

    assert result == {"name": "demo-repo"}
    assert refresh_calls == 1
    assert captured_tokens == ["ghu_stale", "ghu_fresh"]


@pytest.mark.asyncio
async def test_github_client_returns_unable_to_verify_when_refresh_fails():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    async def failing_refresh() -> str | None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(
            http, token="ghu_stale", refresh_callback=failing_refresh
        )
        result = await client.get_repo_info("octo", "demo")

    assert isinstance(result, UnableToVerify)
    assert result.reason == "http_401"


@pytest.mark.asyncio
async def test_github_client_without_refresh_callback_does_not_retry():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(http, token="ghu_x")
        result = await client.get_repo_info("octo", "demo")

    assert calls == 1
    assert isinstance(result, UnableToVerify)
