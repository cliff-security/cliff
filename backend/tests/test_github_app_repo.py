"""Tests for the github_app_installation repository (IMPL-0010, Phase 1)."""

from __future__ import annotations

import aiosqlite
import pytest

from opensec.db import repo_integration
from opensec.db.connection import close_db, init_db
from opensec.integrations.github_app import repo as gh_repo
from opensec.integrations.github_app.models import (
    GithubAppInstallationCreate,
    GithubAppPollingStatus,
)
from opensec.models import IntegrationConfigCreate


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


async def _create_integration_row(
    db: aiosqlite.Connection, *, provider_name: str = "github", enabled: bool = False
) -> str:
    integration = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type="finding_source",
            provider_name=provider_name,
            enabled=enabled,
            config=None,
            action_tier=0,
        ),
    )
    return integration.id


# ---------------------------------------------------------------------------
# create_pending
# ---------------------------------------------------------------------------


async def test_create_pending_inserts_row_and_returns_record(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    record = await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="Iv23liGitHubAppClientId",
            csrf_state="abc-123",
            user_code="MNPQ-RSTU",
            verification_uri="https://github.com/login/device",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    assert record.id
    assert record.integration_id == integration_id
    assert record.app_slug == "opensec"
    assert record.csrf_state == "abc-123"
    assert record.polling_status == "installation_pending"
    assert record.installation_id is None
    assert record.created_at
    assert record.updated_at


async def test_create_pending_rejects_duplicate_csrf(db: aiosqlite.Connection):
    integration_a = await _create_integration_row(db, provider_name="github")
    integration_b = await _create_integration_row(db, provider_name="github-secondary")

    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_a,
            app_slug="opensec",
            client_id="cid",
            csrf_state="dup",
            user_code="AAAA-BBBB",
            verification_uri="https://github.com/login/device",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    with pytest.raises(aiosqlite.IntegrityError):
        await gh_repo.create_pending(
            db,
            GithubAppInstallationCreate(
                integration_id=integration_b,
                app_slug="opensec",
                client_id="cid",
                csrf_state="dup",
                user_code="CCCC-DDDD",
                verification_uri="https://github.com/login/device",
                device_code_expires_at="2026-05-07T12:00:00+00:00",
                polling_interval_seconds=5,
            ),
        )


async def test_create_pending_rejects_duplicate_integration_id(
    db: aiosqlite.Connection,
):
    integration_id = await _create_integration_row(db)

    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state-1",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    with pytest.raises(aiosqlite.IntegrityError):
        await gh_repo.create_pending(
            db,
            GithubAppInstallationCreate(
                integration_id=integration_id,
                app_slug="opensec",
                client_id="cid",
                csrf_state="state-2",
                user_code="B",
                verification_uri="v",
                device_code_expires_at="2026-05-07T12:00:00+00:00",
                polling_interval_seconds=5,
            ),
        )


# ---------------------------------------------------------------------------
# get_inflight / get_for_integration / get_by_csrf
# ---------------------------------------------------------------------------


async def test_get_for_integration_returns_none_when_missing(
    db: aiosqlite.Connection,
):
    integration_id = await _create_integration_row(db)
    assert await gh_repo.get_for_integration(db, integration_id) is None


async def test_get_for_integration_returns_record(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="s",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    assert record.integration_id == integration_id


async def test_get_by_csrf_returns_record(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="csrf-token-x",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.get_by_csrf(db, "csrf-token-x")
    assert record is not None
    assert record.csrf_state == "csrf-token-x"


async def test_get_by_csrf_returns_none_for_unknown(db: aiosqlite.Connection):
    assert await gh_repo.get_by_csrf(db, "nope") is None


async def test_get_inflight_returns_only_non_terminal(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    inflight = await gh_repo.get_inflight(db, integration_id)
    assert inflight is not None

    await gh_repo.update_polling_status(
        db, integration_id, status="connected", error=None
    )
    inflight = await gh_repo.get_inflight(db, integration_id)
    assert inflight is None


# ---------------------------------------------------------------------------
# attach_installation_id
# ---------------------------------------------------------------------------


async def test_attach_installation_id_updates_row(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    updated = await gh_repo.attach_installation_id(
        db, csrf_state="state", installation_id=12345
    )
    assert updated is not None
    assert updated.installation_id == 12345
    assert updated.installation_completed_at is not None


async def test_attach_installation_id_returns_none_for_unknown_state(
    db: aiosqlite.Connection,
):
    assert (
        await gh_repo.attach_installation_id(
            db, csrf_state="missing", installation_id=1
        )
        is None
    )


# ---------------------------------------------------------------------------
# mark_connected / mark_failed
# ---------------------------------------------------------------------------


async def test_mark_connected_sets_status_and_login(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.mark_connected(
        db,
        integration_id,
        github_login="octocat",
        token_expires_at=None,
    )
    assert record is not None
    assert record.polling_status == "connected"
    assert record.github_login == "octocat"
    assert record.connected_at is not None
    assert record.last_validated_at is not None


async def test_mark_failed_sets_terminal_status_and_error(
    db: aiosqlite.Connection,
):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.mark_failed(
        db, integration_id, status="denied", error="user_denied"
    )
    assert record is not None
    assert record.polling_status == "denied"
    assert record.polling_error == "user_denied"


@pytest.mark.parametrize("status", ["connected", "expired", "denied", "error"])
async def test_get_inflight_excludes_all_terminal_states(
    db: aiosqlite.Connection, status: GithubAppPollingStatus
):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    await gh_repo.update_polling_status(db, integration_id, status=status, error=None)
    assert await gh_repo.get_inflight(db, integration_id) is None


# ---------------------------------------------------------------------------
# update_polling_status / update_interval
# ---------------------------------------------------------------------------


async def test_update_polling_status_writes_status_and_error(
    db: aiosqlite.Connection,
):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.update_polling_status(
        db, integration_id, status="device_pending", error=None
    )
    assert record is not None
    assert record.polling_status == "device_pending"
    assert record.polling_error is None
    assert record.last_polled_at is not None


async def test_update_interval_increments_seconds(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    record = await gh_repo.update_interval(db, integration_id, interval_seconds=10)
    assert record is not None
    assert record.polling_interval_seconds == 10


# ---------------------------------------------------------------------------
# delete + cascade
# ---------------------------------------------------------------------------


async def test_delete_removes_row(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )
    assert await gh_repo.delete(db, integration_id) is True
    assert await gh_repo.get_for_integration(db, integration_id) is None


async def test_delete_returns_false_when_missing(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    assert await gh_repo.delete(db, integration_id) is False


async def test_cascade_on_integration_delete(db: aiosqlite.Connection):
    integration_id = await _create_integration_row(db)
    await gh_repo.create_pending(
        db,
        GithubAppInstallationCreate(
            integration_id=integration_id,
            app_slug="opensec",
            client_id="cid",
            csrf_state="state",
            user_code="A",
            verification_uri="v",
            device_code_expires_at="2026-05-07T12:00:00+00:00",
            polling_interval_seconds=5,
        ),
    )

    deleted = await repo_integration.delete_integration(db, integration_id)
    assert deleted is True
    assert await gh_repo.get_for_integration(db, integration_id) is None


# ---------------------------------------------------------------------------
# Helper: list other enabled github integrations (for PAT archive)
# ---------------------------------------------------------------------------


async def test_list_other_enabled_github_integrations(db: aiosqlite.Connection):
    new_app = await _create_integration_row(db, provider_name="github", enabled=False)
    pat_a = await _create_integration_row(db, provider_name="github", enabled=True)
    pat_b = await _create_integration_row(db, provider_name="github", enabled=True)
    await _create_integration_row(db, provider_name="snyk", enabled=True)
    await _create_integration_row(db, provider_name="github", enabled=False)

    others = await gh_repo.list_other_enabled_github_integrations(db, exclude_id=new_app)
    other_ids = {i.id for i in others}
    assert pat_a in other_ids
    assert pat_b in other_ids
    assert new_app not in other_ids
