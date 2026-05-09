"""DeviceFlowOrchestrator — drives the device-flow state machine (IMPL-0010).

The orchestrator owns:

- Initiating the flow (call ``request_device_code``, persist a pending
  row, encrypt the device_code into the credential vault).
- Attaching the GitHub-issued ``installation_id`` from the App-install
  ``setup_url`` callback (CSRF-validated).
- A single polling step (``run_poll_step``), and a background task
  (``start``) that ticks ``run_poll_step`` on the GitHub-supplied
  interval until the flow reaches a terminal state.
- Disconnecting (cancel task + clear credentials + delete row +
  disable integration).

The user access token is stored under the existing
``github_personal_access_token`` key — same one the MCP Gateway
substitutes (ADR-0018) — so workspaces transparently keep working.
The refresh token (when present) lives under ``github_refresh_token``.
The in-flight ``device_code`` is encrypted via the vault under
``github_device_code`` and cleared on terminal state.

In-process state: a small in-memory map of running asyncio tasks keyed
by ``integration_id``. The flow window is at most 15 minutes; if the
process restarts mid-flow the row's ``device_code_expires_at`` will
naturally tick to ``expired`` on the next /status request and the user
clicks "Try again". No durable task queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from opensec.db import repo_integration
from opensec.integrations.audit import AuditEvent
from opensec.integrations.github_app import repo as gh_repo
from opensec.integrations.github_app.client import TRANSIENT_ERRORS as _TRANSIENT_ERRORS
from opensec.integrations.github_app.models import (
    GithubAppInstallationCreate,
)
from opensec.models import IntegrationConfigUpdate

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from opensec.integrations.audit import AuditLogger
    from opensec.integrations.github_app.client import (
        DeviceCodeResponse,
        PollTokenResult,
        UserInfo,
    )
    from opensec.integrations.github_app.models import GithubAppInstallation
    from opensec.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)

GITHUB_TOKEN_KEY = "github_personal_access_token"
GITHUB_REFRESH_KEY = "github_refresh_token"  # noqa: S105 — vault key name, not a credential
GITHUB_DEVICE_CODE_KEY = "github_device_code"

CSRF_BYTES = 24


class InstallationCsrfMismatchError(RuntimeError):
    """Raised when /setup is hit with a CSRF state we never issued."""


class GithubAppClientProtocol(Protocol):
    async def request_device_code(self) -> DeviceCodeResponse: ...
    async def poll_token(self, *, device_code: str) -> PollTokenResult: ...
    async def fetch_user(self, *, access_token: str) -> UserInfo: ...


class _Clock(Protocol):
    def time(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class _RealClock:
    def time(self) -> float:
        return _time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True)
class DeviceFlowStartResult:
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    csrf_state: str


class DeviceFlowOrchestrator:
    """State machine + background polling for the GitHub App device flow."""

    def __init__(
        self,
        *,
        db: aiosqlite.Connection,
        vault: CredentialVault,
        audit: AuditLogger,
        client_factory: Callable[[], GithubAppClientProtocol],
        app_slug: str,
        client_id: str,
        clock: _Clock | None = None,
    ) -> None:
        self._db = db
        self._vault = vault
        self._audit = audit
        self._client_factory = client_factory
        self._app_slug = app_slug
        self._client_id = client_id
        self._clock: _Clock = clock or _RealClock()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Clock helpers — keep wall-clock decisions consistent with tests
    # ------------------------------------------------------------------

    def _now_dt(self) -> datetime:
        return datetime.fromtimestamp(self._clock.time(), tz=UTC)

    def _expires_at_iso(self, seconds_from_now: int) -> str:
        return (self._now_dt() + timedelta(seconds=seconds_from_now)).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initiate(self, integration_id: str) -> DeviceFlowStartResult:
        """Start (or resume) the device flow for *integration_id*.

        Idempotent — if a non-terminal row already exists, returns its
        cached state rather than asking GitHub for a new device code
        (avoids rate-limiting on rapid double-clicks).
        """
        existing = await gh_repo.get_inflight(self._db, integration_id)
        if existing is not None:
            return DeviceFlowStartResult(
                user_code=existing.user_code or "",
                verification_uri=existing.verification_uri or "",
                expires_in=self._remaining_seconds(existing),
                interval=existing.polling_interval_seconds or 5,
                csrf_state=existing.csrf_state,
            )

        # Wipe any stale terminal row before re-issuing — keeps a single
        # row per integration (UNIQUE constraint also guarantees this).
        await gh_repo.delete(self._db, integration_id)

        client = self._client_factory()
        device = await client.request_device_code()
        csrf_state = secrets.token_urlsafe(CSRF_BYTES)

        await gh_repo.create_pending(
            self._db,
            GithubAppInstallationCreate(
                integration_id=integration_id,
                app_slug=self._app_slug,
                client_id=self._client_id,
                csrf_state=csrf_state,
                user_code=device.user_code,
                verification_uri=device.verification_uri,
                device_code_expires_at=self._expires_at_iso(device.expires_in),
                polling_interval_seconds=device.interval,
            ),
        )
        await self._vault.store(
            integration_id, GITHUB_DEVICE_CODE_KEY, device.device_code
        )
        await self._audit.log(
            AuditEvent(
                event_type="github_app.connect_initiated",
                integration_id=integration_id,
                provider_name="github",
                status="success",
            )
        )
        await self._audit.log(
            AuditEvent(
                event_type="github_app.device_code_issued",
                integration_id=integration_id,
                provider_name="github",
                status="success",
            )
        )

        return DeviceFlowStartResult(
            user_code=device.user_code,
            verification_uri=device.verification_uri,
            expires_in=device.expires_in,
            interval=device.interval,
            csrf_state=csrf_state,
        )

    async def attach_installation(
        self, *, csrf_state: str, installation_id: int
    ) -> GithubAppInstallation:
        record = await gh_repo.attach_installation_id(
            self._db, csrf_state=csrf_state, installation_id=installation_id
        )
        if record is None:
            raise InstallationCsrfMismatchError(
                f"unknown CSRF state {csrf_state!r}"
            )
        await self._audit.log(
            AuditEvent(
                event_type="github_app.installation_completed",
                integration_id=record.integration_id,
                provider_name="github",
                status="success",
            )
        )
        return record

    async def run_poll_step(self, integration_id: str) -> None:
        """Execute one polling tick. Idempotent on terminal rows (no-op)."""
        record = await gh_repo.get_for_integration(self._db, integration_id)
        if record is None:
            return
        if record.polling_status not in {"installation_pending", "device_pending"}:
            return  # terminal, nothing to do

        # Device-code expiry — short-circuit before hitting the network.
        if self._is_expired(record):
            await self._terminate(integration_id, status="expired", error=None)
            return

        try:
            device_code = await self._vault.retrieve(
                integration_id, GITHUB_DEVICE_CODE_KEY
            )
        except KeyError:
            await self._terminate(
                integration_id, status="error", error="device_code_missing"
            )
            return

        client = self._client_factory()
        try:
            result = await client.poll_token(device_code=device_code)
        except _TRANSIENT_ERRORS as exc:
            # Network blip / GitHub 429 / 5xx — these are recoverable.
            # Don't terminate: log, leave status as-is, the next tick on
            # the polling loop will retry. The 15-minute device-code
            # window bounds how long we keep retrying.
            logger.info(
                "poll_token transient failure for %s (%s); will retry on next tick",
                integration_id,
                exc.__class__.__name__,
            )
            return
        except Exception as exc:  # noqa: BLE001 — anything else is terminal
            logger.warning(
                "poll_token unrecoverable failure for %s: %s", integration_id, exc
            )
            await self._terminate(integration_id, status="error", error=str(exc))
            return

        await self._apply_poll_result(record, result, client)

    async def disconnect(self, integration_id: str) -> None:
        # Order matters: disable the integration_config FIRST so no
        # downstream consumer (workspaces.py, _engine_dep, etc.) can
        # pick up the row in a half-deleted state where the credentials
        # are gone but ``enabled`` is still ``True``.
        await repo_integration.update_integration(
            self._db, integration_id, IntegrationConfigUpdate(enabled=False)
        )
        await self.stop(integration_id)
        # Vault deletes are independent — fan them out and swallow
        # individual misses (a key may not exist if the user disconnects
        # before the device flow completed).
        await asyncio.gather(
            self._vault.delete(integration_id, GITHUB_TOKEN_KEY),
            self._vault.delete(integration_id, GITHUB_REFRESH_KEY),
            self._vault.delete(integration_id, GITHUB_DEVICE_CODE_KEY),
            return_exceptions=True,
        )
        await gh_repo.delete(self._db, integration_id)
        await self._audit.log(
            AuditEvent(
                event_type="github_app.disconnect",
                integration_id=integration_id,
                provider_name="github",
                status="success",
            )
        )

    async def start(self, integration_id: str) -> None:
        """Spawn a background polling task. No-op if one is already running."""
        if integration_id in self._tasks and not self._tasks[integration_id].done():
            return
        self._tasks[integration_id] = asyncio.create_task(
            self._poll_loop(integration_id)
        )

    async def stop(self, integration_id: str) -> None:
        task = self._tasks.pop(integration_id, None)
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def stop_all(self) -> None:
        for integration_id in list(self._tasks):
            await self.stop(integration_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _poll_loop(self, integration_id: str) -> None:
        while True:
            record = await gh_repo.get_for_integration(self._db, integration_id)
            if record is None:
                return
            if record.polling_status not in {
                "installation_pending",
                "device_pending",
            }:
                return
            interval = record.polling_interval_seconds or 5
            await self._clock.sleep(float(interval))
            await self.run_poll_step(integration_id)

    async def _apply_poll_result(
        self,
        record: GithubAppInstallation,
        result: PollTokenResult,
        client: GithubAppClientProtocol,
    ) -> None:
        integration_id = record.integration_id
        kind = result.kind

        if kind == "success":
            assert result.access_token is not None
            await self._vault.store(
                integration_id, GITHUB_TOKEN_KEY, result.access_token
            )
            if result.refresh_token:
                await self._vault.store(
                    integration_id, GITHUB_REFRESH_KEY, result.refresh_token
                )
            with contextlib.suppress(KeyError):
                await self._vault.delete(integration_id, GITHUB_DEVICE_CODE_KEY)

            github_login: str | None = None
            try:
                user = await client.fetch_user(access_token=result.access_token)
                github_login = user.login
            except Exception as exc:  # noqa: BLE001 — login is a nicety
                logger.warning("fetch_user failed post-connect: %s", exc)

            token_expires_at = (
                self._expires_at_iso(result.expires_in) if result.expires_in else None
            )

            await gh_repo.mark_connected(
                self._db,
                integration_id,
                github_login=github_login,
                token_expires_at=token_expires_at,
            )
            await repo_integration.update_integration(
                self._db,
                integration_id,
                IntegrationConfigUpdate(enabled=True),
            )

            # Archive any other enabled github integrations (PAT migration).
            others = await gh_repo.list_other_enabled_github_integrations(
                self._db, exclude_id=integration_id
            )
            for other in others:
                await repo_integration.update_integration(
                    self._db,
                    other.id,
                    IntegrationConfigUpdate(enabled=False),
                )
                await self._audit.log(
                    AuditEvent(
                        event_type="github_app.pat_archived",
                        integration_id=other.id,
                        provider_name="github",
                        status="success",
                    )
                )

            await self._audit.log(
                AuditEvent(
                    event_type="github_app.token_received",
                    integration_id=integration_id,
                    provider_name="github",
                    status="success",
                )
            )
            return

        if kind == "authorization_pending":
            # Reflect whichever pending stage we're in (installation_pending
            # or device_pending — driven by whether installation_id is set).
            new_status = (
                "device_pending" if record.installation_id else "installation_pending"
            )
            await gh_repo.update_polling_status(
                self._db, integration_id, status=new_status, error=None
            )
            return

        if kind == "slow_down":
            new_interval = result.interval or (
                (record.polling_interval_seconds or 5) + 5
            )
            await gh_repo.update_interval(
                self._db, integration_id, interval_seconds=new_interval
            )
            return

        if kind == "expired_token":
            await self._terminate(integration_id, status="expired", error=None)
            return

        if kind == "access_denied":
            await self._terminate(integration_id, status="denied", error=None)
            return

        # Defensive — unknown kind should never reach here (client raises).
        await self._terminate(
            integration_id, status="error", error=f"unknown_kind:{kind}"
        )

    async def _terminate(
        self,
        integration_id: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        with contextlib.suppress(KeyError):
            await self._vault.delete(integration_id, GITHUB_DEVICE_CODE_KEY)
        await gh_repo.update_polling_status(
            self._db, integration_id, status=status, error=error  # type: ignore[arg-type]
        )

    def _is_expired(self, record: GithubAppInstallation) -> bool:
        if not record.device_code_expires_at:
            return False
        try:
            expires = datetime.fromisoformat(record.device_code_expires_at)
        except ValueError:
            return False
        return self._now_dt() >= expires

    def _remaining_seconds(self, record: GithubAppInstallation) -> int:
        if not record.device_code_expires_at:
            return 0
        try:
            expires = datetime.fromisoformat(record.device_code_expires_at)
        except ValueError:
            return 0
        delta = (expires - self._now_dt()).total_seconds()
        return max(int(delta), 0)


# ---------------------------------------------------------------------------
# Refresh helper (Phase 5)
# ---------------------------------------------------------------------------


async def refresh_user_access_token(
    *,
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
    client: GithubAppClientProtocol,
    integration_id: str,
) -> str | None:
    """Refresh the user access token in place. Returns the new token, or
    ``None`` when no refresh token is stored for *integration_id*.

    On the success path the new access token (and any new refresh token)
    are re-encrypted into the vault under the same keys the MCP gateway
    already substitutes - workspaces stay oblivious.

    Any exception from the GitHub client is re-raised after marking the
    installation row ``polling_status='error'`` with
    ``polling_error='needs_reconnect'``, so the UI can surface a
    "reconnect required" affordance.
    """
    if not await vault.has_credential(integration_id, GITHUB_REFRESH_KEY):
        return None
    refresh_token = await vault.retrieve(integration_id, GITHUB_REFRESH_KEY)

    try:
        result = await client.refresh_access_token(refresh_token=refresh_token)  # type: ignore[attr-defined]
    except Exception:
        await gh_repo.update_polling_status(
            db,
            integration_id,
            status="error",
            error="needs_reconnect",
        )
        await audit.log(
            AuditEvent(
                event_type="github_app.token_refresh_failed",
                integration_id=integration_id,
                provider_name="github",
                status="error",
            )
        )
        raise

    if result.kind != "success" or not result.access_token:
        await gh_repo.update_polling_status(
            db,
            integration_id,
            status="error",
            error="needs_reconnect",
        )
        return None

    await vault.store(integration_id, GITHUB_TOKEN_KEY, result.access_token)
    if result.refresh_token:
        await vault.store(integration_id, GITHUB_REFRESH_KEY, result.refresh_token)
    await audit.log(
        AuditEvent(
            event_type="github_app.token_refreshed",
            integration_id=integration_id,
            provider_name="github",
            status="success",
        )
    )
    return result.access_token
