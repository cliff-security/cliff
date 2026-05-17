"""Tests for DeviceFlowOrchestrator (IMPL-0010, Phase 3).

Drive the full state machine using a fake clock and a fake
GitHubDeviceFlowClient so we can step through every transition
deterministically.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import pytest

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
    DeviceFlowOrchestrator,
    InstallationCsrfMismatchError,
)
from cliff.integrations.vault import CredentialVault
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite

VAULT_KEY = b"\x00" * 32
GITHUB_TOKEN_KEY = "github_personal_access_token"
GITHUB_REFRESH_KEY = "github_refresh_token"  # noqa: S105 — vault key name, not a credential
GITHUB_DEVICE_CODE_KEY = "github_device_code"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, *, start: float = 1_000_000.0) -> None:
        self._t = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self._t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._t += seconds

    def advance(self, seconds: float) -> None:
        self._t += seconds


class FakeGitHubClient:
    """Hand-driven fake — request_device_code returns a single canned
    response; poll_token returns the next item from a deque (deterministic
    ordering); fetch_user always succeeds.
    """

    def __init__(self) -> None:
        self.device_code_response = DeviceCodeResponse(
            device_code="DEV-XYZ",
            user_code="MNPQ-RSTU",
            verification_uri="https://github.com/login/device",
            expires_in=900,
            interval=5,
        )
        self.poll_results: deque[PollTokenResult] = deque()
        self.user_info = UserInfo(login="octocat", id=1)
        self.poll_calls = 0

    async def request_device_code(self) -> DeviceCodeResponse:
        return self.device_code_response

    async def poll_token(self, *, device_code: str) -> PollTokenResult:
        self.poll_calls += 1
        return self.poll_results.popleft()

    async def fetch_user(self, *, access_token: str) -> UserInfo:
        return self.user_info


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def audit(db: aiosqlite.Connection):
    a = AuditLogger(db)
    await a.start()
    yield a
    await a.stop()


@pytest.fixture
async def vault(db: aiosqlite.Connection):
    return CredentialVault(db, key=VAULT_KEY)


@pytest.fixture
async def integration_id(db: aiosqlite.Connection) -> str:
    integ = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="github",
            enabled=False,
            config=None,
            action_tier=0,
        ),
    )
    return integ.id


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_client() -> FakeGitHubClient:
    return FakeGitHubClient()


@pytest.fixture
def orchestrator(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    fake_client: FakeGitHubClient,
    fake_clock: FakeClock,
) -> DeviceFlowOrchestrator:
    return DeviceFlowOrchestrator(
        db=db,
        vault=vault,
        audit=audit,
        client_factory=lambda: fake_client,
        app_slug="cliff",
        client_id="Iv23liTestId",
        clock=fake_clock,
    )


# ---------------------------------------------------------------------------
# initiate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_creates_pending_row_with_initial_state(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    integration_id: str,
):
    result = await orchestrator.initiate(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"
    assert record.user_code == "MNPQ-RSTU"
    assert record.csrf_state == result.csrf_state


@pytest.mark.asyncio
async def test_initiate_stores_device_code_in_vault(
    orchestrator: DeviceFlowOrchestrator,
    vault: CredentialVault,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    stored = await vault.retrieve(integration_id, GITHUB_DEVICE_CODE_KEY)
    assert stored == "DEV-XYZ"


@pytest.mark.asyncio
async def test_initiate_is_idempotent_for_existing_inflight(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    first = await orchestrator.initiate(integration_id)
    # Calling initiate again does NOT request a new device code.
    fake_client.device_code_response = DeviceCodeResponse(
        device_code="SECOND",
        user_code="ZZZZ-YYYY",
        verification_uri="https://github.com/login/device",
        expires_in=900,
        interval=5,
    )
    second = await orchestrator.initiate(integration_id)
    assert second.user_code == first.user_code
    assert second.csrf_state == first.csrf_state


# ---------------------------------------------------------------------------
# attach_installation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_installation_requires_matching_csrf(
    orchestrator: DeviceFlowOrchestrator, integration_id: str
):
    await orchestrator.initiate(integration_id)
    with pytest.raises(InstallationCsrfMismatchError):
        await orchestrator.attach_installation(
            csrf_state="bogus", installation_id=42
        )


@pytest.mark.asyncio
async def test_attach_installation_advances_to_device_pending(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    integration_id: str,
):
    started = await orchestrator.initiate(integration_id)
    record = await orchestrator.attach_installation(
        csrf_state=started.csrf_state, installation_id=42
    )
    assert record.installation_id == 42
    assert record.polling_status == "device_pending"

    # idempotent: a second attach with the same csrf returns the row
    # unchanged (no exception).
    again = await orchestrator.attach_installation(
        csrf_state=started.csrf_state, installation_id=42
    )
    assert again.installation_id == 42


# ---------------------------------------------------------------------------
# Polling state machine — driven by run_poll_step (single-step helper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_step_success_stores_token_under_correct_keys(
    orchestrator: DeviceFlowOrchestrator,
    vault: CredentialVault,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(
            kind="success",
            access_token="ghu_test",
            refresh_token=None,
            expires_in=None,
        )
    )
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "connected"
    assert record.github_login == "octocat"
    assert await vault.retrieve(integration_id, GITHUB_TOKEN_KEY) == "ghu_test"
    # No refresh token in this scenario.
    assert not await vault.has_credential(integration_id, GITHUB_REFRESH_KEY)


@pytest.mark.asyncio
async def test_poll_step_success_stores_refresh_token_when_present(
    orchestrator: DeviceFlowOrchestrator,
    vault: CredentialVault,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(
            kind="success",
            access_token="ghu_main",
            refresh_token="ghr_refresh",
            expires_in=28800,
        )
    )
    await orchestrator.run_poll_step(integration_id)

    assert await vault.retrieve(integration_id, GITHUB_REFRESH_KEY) == "ghr_refresh"


@pytest.mark.asyncio
async def test_poll_step_success_marks_integration_enabled(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="success", access_token="ghu_x")
    )
    await orchestrator.run_poll_step(integration_id)

    integ = await repo_integration.get_integration(db, integration_id)
    assert integ is not None
    assert integ.enabled is True


@pytest.mark.asyncio
async def test_poll_step_success_clears_device_code_from_vault(
    orchestrator: DeviceFlowOrchestrator,
    vault: CredentialVault,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="success", access_token="ghu_x")
    )
    await orchestrator.run_poll_step(integration_id)

    assert not await vault.has_credential(integration_id, GITHUB_DEVICE_CODE_KEY)


@pytest.mark.asyncio
async def test_poll_step_authorization_pending_keeps_status_pending(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="authorization_pending")
    )
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"


@pytest.mark.asyncio
async def test_poll_step_authorization_pending_after_install_is_device_pending(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    started = await orchestrator.initiate(integration_id)
    await orchestrator.attach_installation(
        csrf_state=started.csrf_state, installation_id=99
    )
    fake_client.poll_results.append(
        PollTokenResult(kind="authorization_pending")
    )
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "device_pending"


@pytest.mark.asyncio
async def test_poll_step_slow_down_increments_interval(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="slow_down", interval=10)
    )
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_interval_seconds == 10


@pytest.mark.asyncio
async def test_poll_step_expired_marks_terminal(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(PollTokenResult(kind="expired_token"))
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "expired"


@pytest.mark.asyncio
async def test_poll_step_denied_marks_terminal(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(PollTokenResult(kind="access_denied"))
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "denied"


@pytest.mark.asyncio
async def test_poll_step_unexpected_error_marks_error(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)

    async def raising_poll(*, device_code: str):  # noqa: ARG001
        raise RuntimeError("boom")

    fake_client.poll_token = raising_poll  # type: ignore[assignment]
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "error"
    assert "boom" in (record.polling_error or "")


@pytest.mark.asyncio
async def test_poll_step_transient_network_error_does_not_terminate(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """A transient httpx error (timeout, connect failure, GitHub 5xx) must
    NOT mark the row terminal — the poll loop's next tick gets to retry
    within the 15-minute device-code window."""
    import httpx

    await orchestrator.initiate(integration_id)

    async def transient_poll(*, device_code: str):  # noqa: ARG001
        raise httpx.ConnectError("dns blip")

    fake_client.poll_token = transient_poll  # type: ignore[assignment]
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    # Status stays in the pre-poll state, not flipped to "error".
    assert record.polling_status == "installation_pending"


@pytest.mark.asyncio
async def test_poll_step_transient_github_5xx_does_not_terminate(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    from cliff.integrations.github_app.client import GitHubDeviceFlowTransientError

    await orchestrator.initiate(integration_id)

    async def transient_poll(*, device_code: str):  # noqa: ARG001
        raise GitHubDeviceFlowTransientError("HTTP 503")

    fake_client.poll_token = transient_poll  # type: ignore[assignment]
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"


@pytest.mark.asyncio
async def test_poll_step_after_device_code_expiry_marks_expired(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_clock: FakeClock,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    # Skip past the 15-minute window without queuing any poll results.
    fake_clock.advance(901)
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "expired"


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_clears_credentials_and_installation_row(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    vault: CredentialVault,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(
            kind="success", access_token="ghu_x", refresh_token="ghr_x"
        )
    )
    await orchestrator.run_poll_step(integration_id)

    await orchestrator.disconnect(integration_id)

    assert await gh_repo.get_for_integration(db, integration_id) is None
    assert not await vault.has_credential(integration_id, GITHUB_TOKEN_KEY)
    assert not await vault.has_credential(integration_id, GITHUB_REFRESH_KEY)
    integ = await repo_integration.get_integration(db, integration_id)
    assert integ is not None
    assert integ.enabled is False


# ---------------------------------------------------------------------------
# PAT archive on connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pat_row_archived_after_app_connect(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    # Pre-existing PAT integration (separate row).
    pat = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="github",
            enabled=True,
            config=None,
            action_tier=0,
        ),
    )
    # And an unrelated integration that must NOT be touched.
    unrelated = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name="snyk",
            enabled=True,
            config=None,
            action_tier=0,
        ),
    )

    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="success", access_token="ghu_x")
    )
    await orchestrator.run_poll_step(integration_id)

    # PAT row archived; unrelated row untouched.
    pat_row = await repo_integration.get_integration(db, pat.id)
    other_row = await repo_integration.get_integration(db, unrelated.id)
    assert pat_row is not None
    assert pat_row.enabled is False
    assert other_row is not None
    assert other_row.enabled is True
