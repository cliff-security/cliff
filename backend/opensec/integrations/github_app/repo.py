"""Repository functions for the github_app_installation table (IMPL-0010).

Mirrors the conventions used by the other repos in ``opensec.db`` — async
aiosqlite, ISO 8601 timestamps as TEXT, async commits per write. Lives
under ``opensec.integrations.github_app`` rather than ``opensec.db``
because the table is feature-scoped to one integration; the table itself
still references ``integration_config`` via foreign key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from opensec.integrations.github_app.models import (
    TERMINAL_POLLING_STATUSES,
    GithubAppInstallation,
    GithubAppInstallationCreate,
    GithubAppPollingStatus,
)

if TYPE_CHECKING:
    import aiosqlite

    from opensec.models import IntegrationConfig


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_record(row: aiosqlite.Row) -> GithubAppInstallation:
    return GithubAppInstallation(
        id=row["id"],
        integration_id=row["integration_id"],
        app_slug=row["app_slug"],
        client_id=row["client_id"],
        installation_id=row["installation_id"],
        installation_completed_at=row["installation_completed_at"],
        csrf_state=row["csrf_state"],
        user_code=row["user_code"],
        verification_uri=row["verification_uri"],
        device_code_expires_at=row["device_code_expires_at"],
        polling_interval_seconds=row["polling_interval_seconds"],
        polling_status=row["polling_status"],
        polling_error=row["polling_error"],
        last_polled_at=row["last_polled_at"],
        token_expires_at=row["token_expires_at"],
        github_login=row["github_login"],
        last_validated_at=row["last_validated_at"],
        connected_at=row["connected_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_pending(
    db: aiosqlite.Connection, data: GithubAppInstallationCreate
) -> GithubAppInstallation:
    """Insert a fresh row in installation_pending state. Returns the record."""
    row_id = str(uuid.uuid4())
    now = _now_iso()
    await db.execute(
        """
        INSERT INTO github_app_installation (
            id, integration_id, app_slug, client_id,
            csrf_state, user_code, verification_uri,
            device_code_expires_at, polling_interval_seconds,
            polling_status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'installation_pending', ?, ?)
        """,
        (
            row_id,
            data.integration_id,
            data.app_slug,
            data.client_id,
            data.csrf_state,
            data.user_code,
            data.verification_uri,
            data.device_code_expires_at,
            data.polling_interval_seconds,
            now,
            now,
        ),
    )
    await db.commit()
    record = await get_for_integration(db, data.integration_id)
    assert record is not None  # just inserted
    return record


async def get_for_integration(
    db: aiosqlite.Connection, integration_id: str
) -> GithubAppInstallation | None:
    cursor = await db.execute(
        "SELECT * FROM github_app_installation WHERE integration_id = ?",
        (integration_id,),
    )
    row = await cursor.fetchone()
    return _row_to_record(row) if row else None


async def get_by_csrf(
    db: aiosqlite.Connection, csrf_state: str
) -> GithubAppInstallation | None:
    cursor = await db.execute(
        "SELECT * FROM github_app_installation WHERE csrf_state = ?",
        (csrf_state,),
    )
    row = await cursor.fetchone()
    return _row_to_record(row) if row else None


async def get_inflight(
    db: aiosqlite.Connection, integration_id: str
) -> GithubAppInstallation | None:
    """Return the row only if it's in a non-terminal polling state."""
    record = await get_for_integration(db, integration_id)
    if record is None:
        return None
    if record.polling_status in TERMINAL_POLLING_STATUSES:
        return None
    return record


async def attach_installation_id(
    db: aiosqlite.Connection, *, csrf_state: str, installation_id: int
) -> GithubAppInstallation | None:
    """Record the GitHub-issued installation_id and bump status to device_pending."""
    now = _now_iso()
    cursor = await db.execute(
        """
        UPDATE github_app_installation
        SET installation_id = ?,
            installation_completed_at = ?,
            polling_status = CASE
                WHEN polling_status = 'installation_pending' THEN 'device_pending'
                ELSE polling_status
            END,
            updated_at = ?
        WHERE csrf_state = ?
        """,
        (installation_id, now, now, csrf_state),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    record = await get_by_csrf(db, csrf_state)
    return record


async def update_polling_status(
    db: aiosqlite.Connection,
    integration_id: str,
    *,
    status: GithubAppPollingStatus,
    error: str | None,
) -> GithubAppInstallation | None:
    now = _now_iso()
    await db.execute(
        """
        UPDATE github_app_installation
        SET polling_status = ?,
            polling_error = ?,
            last_polled_at = ?,
            updated_at = ?
        WHERE integration_id = ?
        """,
        (status, error, now, now, integration_id),
    )
    await db.commit()
    return await get_for_integration(db, integration_id)


async def update_interval(
    db: aiosqlite.Connection, integration_id: str, *, interval_seconds: int
) -> GithubAppInstallation | None:
    now = _now_iso()
    await db.execute(
        """
        UPDATE github_app_installation
        SET polling_interval_seconds = ?, updated_at = ?
        WHERE integration_id = ?
        """,
        (interval_seconds, now, integration_id),
    )
    await db.commit()
    return await get_for_integration(db, integration_id)


async def mark_connected(
    db: aiosqlite.Connection,
    integration_id: str,
    *,
    github_login: str | None,
    token_expires_at: str | None,
) -> GithubAppInstallation | None:
    now = _now_iso()
    await db.execute(
        """
        UPDATE github_app_installation
        SET polling_status = 'connected',
            polling_error = NULL,
            github_login = ?,
            token_expires_at = ?,
            connected_at = ?,
            last_validated_at = ?,
            last_polled_at = ?,
            updated_at = ?
        WHERE integration_id = ?
        """,
        (github_login, token_expires_at, now, now, now, now, integration_id),
    )
    await db.commit()
    return await get_for_integration(db, integration_id)


async def mark_failed(
    db: aiosqlite.Connection,
    integration_id: str,
    *,
    status: GithubAppPollingStatus,
    error: str | None,
) -> GithubAppInstallation | None:
    if status not in TERMINAL_POLLING_STATUSES:
        msg = f"mark_failed requires terminal status; got {status!r}"
        raise ValueError(msg)
    return await update_polling_status(
        db, integration_id, status=status, error=error
    )


async def delete(db: aiosqlite.Connection, integration_id: str) -> bool:
    cursor = await db.execute(
        "DELETE FROM github_app_installation WHERE integration_id = ?",
        (integration_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def list_other_enabled_github_integrations(
    db: aiosqlite.Connection, *, exclude_id: str
) -> list[IntegrationConfig]:
    """Return every other enabled integration_config row with provider_name='GitHub'.

    Used by the orchestrator after a successful App connect to archive
    the legacy PAT integration (set ``enabled=False`` — never delete).
    Match the casing the rest of the codebase uses (the PAT path stores
    ``provider_name='GitHub'``); a case-insensitive comparison handles
    legacy lowercase rows from earlier dev DBs without needing a
    migration.
    """
    cursor = await db.execute(
        """
        SELECT * FROM integration_config
        WHERE LOWER(provider_name) = 'github' AND enabled = 1 AND id != ?
        ORDER BY updated_at DESC
        """,
        (exclude_id,),
    )
    rows = await cursor.fetchall()
    # Reuse the row mapper from repo_integration via an inline import to avoid
    # duplicating the model construction.
    from opensec.db.repo_integration import _row_to_integration

    return [_row_to_integration(row) for row in rows]
