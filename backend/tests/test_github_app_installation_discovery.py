"""Tests for post-device-flow installation discovery (ADR-0048, B02).

After the device flow yields a user access token, the orchestrator
discovers the GitHub App ``installation_id`` by calling
``GET /user/installations`` with that token — instead of waiting for the
App's redirect callback, which pins self-host onboarding to one port.

Exactly one installation → connect. Zero → hold in ``installation_pending``
until the user installs the App (a later poll tick catches it). More than
one → hold until the user picks via ``select_installation``.
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
    GitHubDeviceFlowError,
    InstallationInfo,
    PollTokenResult,
    UserInfo,
)
from cliff.integrations.github_app.flow import (
    DeviceFlowOrchestrator,
    InstallationNotAvailableError,
)
from cliff.integrations.vault import CredentialVault
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite

VAULT_KEY = b"\x00" * 32
GITHUB_TOKEN_KEY = "github_personal_access_token"
GITHUB_DEVICE_CODE_KEY = "github_device_code"
APP_SLUG = "cliff"


def _install(installation_id: int, *, app_slug: str = APP_SLUG) -> InstallationInfo:
    return InstallationInfo(
        installation_id=installation_id,
        app_slug=app_slug,
        account_login=f"acct-{installation_id}",
        account_type="Organization",
    )


class FakeGitHubClient:
    """Hand-driven fake. ``installations`` and ``list_installations_error``
    let each test stage the discovery outcome independently of the device
    flow's ``poll_results``.
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
        self.installations: list[InstallationInfo] = [_install(4242)]
        self.list_installations_error: Exception | None = None
        self.list_installations_calls = 0

    async def request_device_code(self) -> DeviceCodeResponse:
        return self.device_code_response

    async def poll_token(self, *, device_code: str) -> PollTokenResult:  # noqa: ARG002
        return self.poll_results.popleft()

    async def fetch_user(self, *, access_token: str) -> UserInfo:  # noqa: ARG002
        return self.user_info

    async def list_installations(
        self, *, access_token: str  # noqa: ARG002
    ) -> list[InstallationInfo]:
        self.list_installations_calls += 1
        if self.list_installations_error is not None:
            raise self.list_installations_error
        return self.installations


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
def fake_client() -> FakeGitHubClient:
    return FakeGitHubClient()


@pytest.fixture
def orchestrator(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    fake_client: FakeGitHubClient,
) -> DeviceFlowOrchestrator:
    return DeviceFlowOrchestrator(
        db=db,
        vault=vault,
        audit=audit,
        client_factory=lambda: fake_client,
        app_slug=APP_SLUG,
        client_id="Iv23liTestId",
    )


async def _drive_device_flow_to_success(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
) -> None:
    """initiate → one ``success`` poll. The discovery step runs inside
    that poll."""
    await orchestrator.initiate(integration_id)
    fake_client.poll_results.append(
        PollTokenResult(kind="success", access_token="ghu_test")
    )
    await orchestrator.run_poll_step(integration_id)


# ---------------------------------------------------------------------------
# Discovery on device-flow success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_installation_connects_and_records_id(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """Exactly one installation discovered → the row connects and the
    discovered installation_id is persisted — no redirect callback."""
    fake_client.installations = [_install(99001)]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "connected"
    assert record.installation_id == 99001
    assert record.github_login == "octocat"
    integ = await repo_integration.get_integration(db, integration_id)
    assert integ is not None
    assert integ.enabled is True


@pytest.mark.asyncio
async def test_zero_installations_holds_in_installation_pending(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    vault: CredentialVault,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """No installation yet → keep the row non-terminal with the token
    stored, integration NOT enabled. The user still has to install."""
    fake_client.installations = []
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"
    assert record.installation_id is None
    # github_login is set — that's how the UI tells "awaiting install"
    # apart from the pre-authorization phase.
    assert record.github_login == "octocat"
    # Token is kept so the discovery poll can re-query.
    assert await vault.retrieve(integration_id, GITHUB_TOKEN_KEY) == "ghu_test"
    integ = await repo_integration.get_integration(db, integration_id)
    assert integ is not None
    assert integ.enabled is False


@pytest.mark.asyncio
async def test_many_installations_holds_for_picker(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """More than one installation → don't guess; hold for the picker."""
    fake_client.installations = [_install(1), _install(2), _install(3)]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"
    assert record.installation_id is None


@pytest.mark.asyncio
async def test_discovery_filters_to_our_app_slug(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """``/user/installations`` returns installations of *every* App the
    user authorized — only ours counts toward the 0/1/many decision."""
    fake_client.installations = [
        _install(50, app_slug="some-other-app"),
        _install(777, app_slug=APP_SLUG),
        _install(51, app_slug="yet-another-app"),
    ]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "connected"
    assert record.installation_id == 777


@pytest.mark.asyncio
async def test_discovery_failure_keeps_row_pending_with_token(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    vault: CredentialVault,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """If the ``/user/installations`` call fails, the row must not go
    terminal — the token is kept and the poll loop retries."""
    fake_client.list_installations_error = GitHubDeviceFlowError("HTTP 503")
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"
    assert await vault.retrieve(integration_id, GITHUB_TOKEN_KEY) == "ghu_test"


@pytest.mark.asyncio
async def test_callback_bound_installation_skips_discovery(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """When the legacy /setup callback already bound an installation_id,
    the success path connects directly and never calls discovery."""
    started = await orchestrator.initiate(integration_id)
    await orchestrator.attach_installation(
        csrf_state=started.csrf_state, installation_id=314159
    )
    fake_client.poll_results.append(
        PollTokenResult(kind="success", access_token="ghu_test")
    )
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "connected"
    assert record.installation_id == 314159
    assert fake_client.list_installations_calls == 0


# ---------------------------------------------------------------------------
# Background re-discovery (the 0 → 1 transition)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_step_rediscovers_after_user_installs(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """Row sits in installation_pending with a token (0 installs). The
    user installs the App; the next poll tick discovers it and connects —
    no device-code poll, no callback."""
    fake_client.installations = []
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)
    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "installation_pending"

    # User installs the App — it now shows up in /user/installations.
    fake_client.installations = [_install(880088)]
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.polling_status == "connected"
    assert record.installation_id == 880088


@pytest.mark.asyncio
async def test_poll_step_does_not_touch_device_code_endpoint_post_token(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """Once a token exists the poll step must NOT consult poll_token —
    the device_code was consumed. (poll_results is left empty; a
    regression that polled it would raise IndexError.)"""
    fake_client.installations = []
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)
    # poll_results deque is now empty — a device-code poll here would
    # IndexError. The discovery path must be taken instead.
    await orchestrator.run_poll_step(integration_id)  # must not raise


# ---------------------------------------------------------------------------
# Picker — select_installation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_installation_binds_chosen_and_connects(
    orchestrator: DeviceFlowOrchestrator,
    db: aiosqlite.Connection,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    fake_client.installations = [_install(11), _install(22), _install(33)]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    record = await orchestrator.select_installation(integration_id, 22)
    assert record.polling_status == "connected"
    assert record.installation_id == 22
    integ = await repo_integration.get_integration(db, integration_id)
    assert integ is not None
    assert integ.enabled is True


@pytest.mark.asyncio
async def test_select_installation_rejects_id_user_cannot_administer(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """A hostile/typo'd installation_id not in the user's live set is
    rejected — the user can only bind installations they control."""
    fake_client.installations = [_install(11), _install(22)]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    with pytest.raises(InstallationNotAvailableError):
        await orchestrator.select_installation(integration_id, 99999)


@pytest.mark.asyncio
async def test_select_installation_rejects_other_apps_installation(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    """An installation of a *different* App is not selectable even though
    the user can see it — the slug filter applies to the picker too."""
    fake_client.installations = [
        _install(11),
        _install(22),
        _install(8888, app_slug="some-other-app"),
    ]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)

    with pytest.raises(InstallationNotAvailableError):
        await orchestrator.select_installation(integration_id, 8888)


# ---------------------------------------------------------------------------
# list_available_installations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_available_installations_returns_only_our_app(
    orchestrator: DeviceFlowOrchestrator,
    fake_client: FakeGitHubClient,
    integration_id: str,
):
    fake_client.installations = [_install(11), _install(99, app_slug="other")]
    await _drive_device_flow_to_success(orchestrator, fake_client, integration_id)
    # Re-stage so the explicit list call sees two-of-ours.
    fake_client.installations = [_install(11), _install(12), _install(99, app_slug="other")]

    available = await orchestrator.list_available_installations(integration_id)
    assert {i.installation_id for i in available} == {11, 12}


@pytest.mark.asyncio
async def test_list_available_installations_empty_without_token(
    orchestrator: DeviceFlowOrchestrator,
    integration_id: str,
):
    """Before the device flow produces a token there is nothing to query
    against — return an empty list rather than erroring."""
    await orchestrator.initiate(integration_id)
    available = await orchestrator.list_available_installations(integration_id)
    assert available == []
