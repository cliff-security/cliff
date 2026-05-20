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

from cliff.db import repo_integration
from cliff.integrations.audit import AuditEvent
from cliff.integrations.github_app import repo as gh_repo
from cliff.integrations.github_app.client import TRANSIENT_ERRORS as _TRANSIENT_ERRORS
from cliff.integrations.github_app.models import (
    GithubAppInstallationCreate,
)
from cliff.models import IntegrationConfigUpdate

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.github_app.client import (
        DeviceCodeResponse,
        InstallationInfo,
        PollTokenResult,
        UserInfo,
    )
    from cliff.integrations.github_app.models import GithubAppInstallation
    from cliff.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)

GITHUB_TOKEN_KEY = "github_personal_access_token"
GITHUB_REFRESH_KEY = "github_refresh_token"  # noqa: S105 — vault key name, not a credential
GITHUB_DEVICE_CODE_KEY = "github_device_code"

CSRF_BYTES = 24

# SR-4: cap how many characters of an error message we persist into
# ``github_app_installation.polling_error``. Anything longer is almost
# always a server error page that bloats the row without adding signal.
_POLLING_ERROR_MAX_CHARS = 200

# Hard ceiling on how long a single background ``_poll_loop`` task lives.
# Covers the 15-minute device-code window plus a generous tail for the
# ADR-0048 installation-discovery phase (the user goes off to install the
# App). Past this the task simply stops — the row is left as-is, so a
# returning user's idempotent /connect re-spawns the loop. Without this
# cap an authorized-but-never-installed flow would poll GitHub forever.
_POLL_LOOP_MAX_SECONDS = 30 * 60


class InstallationCsrfMismatchError(RuntimeError):
    """Raised when /setup is hit with a CSRF state we never issued."""


class IntegrationAlreadyConnectedError(RuntimeError):
    """Raised when ``initiate`` is called for a row already in ``connected``.

    Without this guard the existing installation would be silently
    deleted and a fresh device code issued — which masquerades as a
    benign "re-auth" but actually nukes ``installation_id`` /
    ``github_login`` until the user re-completes the device flow. The
    UI doesn't expose this path (the catalog tile is hidden when the
    integration is enabled) but a direct API call would otherwise
    succeed silently.
    """


class InstallationNotAvailableError(RuntimeError):
    """Raised when a selected installation isn't bindable by this user.

    Either the device flow hasn't produced a token yet, or the chosen
    ``installation_id`` is not in the set ``/user/installations`` reports
    for the authenticated user — which is the security boundary: a user
    can only adopt an installation they actually control (ADR-0048).
    """


class GithubAppClientProtocol(Protocol):
    async def request_device_code(self) -> DeviceCodeResponse: ...
    async def poll_token(self, *, device_code: str) -> PollTokenResult: ...
    async def fetch_user(self, *, access_token: str) -> UserInfo: ...
    async def list_installations(
        self, *, access_token: str
    ) -> list[InstallationInfo]: ...


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

        # Reject re-initiation against a connected row — silently nuking
        # an active install would invalidate ``installation_id`` and
        # ``github_login`` until the user completes a brand-new device
        # flow, which is a pretty surprising side-effect of POSTing
        # /connect twice. The UI never reaches this path (it hides the
        # Connect tile when the row is enabled) but a direct API call
        # would otherwise succeed silently. The route translates this
        # into a 409 Conflict.
        connected = await gh_repo.get_for_integration(self._db, integration_id)
        if connected is not None and connected.polling_status == "connected":
            raise IntegrationAlreadyConnectedError(
                f"integration {integration_id} is already connected as "
                f"@{connected.github_login or 'unknown'}; disconnect first to re-auth"
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
            # The strict UPDATE in attach_installation_id refuses to bind
            # to a row that's already past ``installation_pending`` (SR-2).
            # That can happen for two legitimate reasons:
            #  1. The user navigated back / refreshed the /setup callback
            #     and we've already attached the same installation_id —
            #     re-load and treat as a no-op.
            #  2. An attacker is replaying a captured csrf_state with a
            #     *different* installation_id — must be rejected.
            existing = await gh_repo.get_by_csrf(self._db, csrf_state)
            if existing is not None and existing.installation_id == installation_id:
                return existing
            raise InstallationCsrfMismatchError(
                f"unknown or replayed CSRF state {csrf_state!r}"
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

        client = self._client_factory()

        # ADR-0048 — once the device flow has produced a user access token
        # the row is in the installation-discovery phase. Re-poll
        # ``/user/installations`` instead of the device-code endpoint
        # (whose device_code we already consumed and deleted on success).
        if await self._vault.has_credential(integration_id, GITHUB_TOKEN_KEY):
            try:
                token = await self._vault.retrieve(integration_id, GITHUB_TOKEN_KEY)
            except KeyError:
                return  # token vanished between the check and the read
            await self._try_resolve_installation(
                integration_id,
                client,
                access_token=token,
                github_login=record.github_login,
                token_expires_at=record.token_expires_at,
                persist_pending=False,
            )
            return

        # B03 — no local-clock expiry short-circuit. ``device_code_expires_at``
        # is GitHub's deadline measured against GitHub's clock; comparing it to
        # a self-hosted container's wall clock (which can be skewed — Q03 saw a
        # +2h drift) expired still-valid codes prematurely. GitHub's own
        # ``expired_token`` poll result is the single source of truth: an
        # expired code returns that kind and ``_apply_poll_result`` terminates
        # the row. The cost is one extra poll call per genuinely-expired code.

        try:
            device_code = await self._vault.retrieve(
                integration_id, GITHUB_DEVICE_CODE_KEY
            )
        except KeyError:
            await self._terminate(
                integration_id, status="error", error="device_code_missing"
            )
            return

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

    async def list_available_installations(
        self, integration_id: str
    ) -> list[InstallationInfo]:
        """Return the App installations the device-flow user can bind.

        Empty when the device flow hasn't produced a token yet, or when
        the user simply hasn't installed the App. Used by the onboarding
        picker (ADR-0048).
        """
        try:
            token = await self._vault.retrieve(integration_id, GITHUB_TOKEN_KEY)
        except KeyError:
            return []
        client = self._client_factory()
        installations = await client.list_installations(access_token=token)
        return self._filter_our_installations(installations)

    async def select_installation(
        self, integration_id: str, installation_id: int
    ) -> GithubAppInstallation:
        """Bind the user-chosen *installation_id* and connect (ADR-0048).

        Re-fetches ``/user/installations`` and rejects any id outside that
        live set — a user can only adopt an installation they control.
        """
        record = await gh_repo.get_for_integration(self._db, integration_id)
        if record is None:
            raise InstallationNotAvailableError(
                f"no GitHub App flow in progress for integration {integration_id}"
            )
        try:
            token = await self._vault.retrieve(integration_id, GITHUB_TOKEN_KEY)
        except KeyError as exc:
            raise InstallationNotAvailableError(
                "the device flow has not produced an access token yet"
            ) from exc
        client = self._client_factory()
        installations = await client.list_installations(access_token=token)
        ours = self._filter_our_installations(installations)
        if installation_id not in {i.installation_id for i in ours}:
            raise InstallationNotAvailableError(
                f"installation {installation_id} is not available to this user"
            )
        return await self._finalize_connected(
            integration_id,
            installation_id=installation_id,
            github_login=record.github_login,
            token_expires_at=record.token_expires_at,
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
        deadline = self._clock.time() + _POLL_LOOP_MAX_SECONDS
        while True:
            record = await gh_repo.get_for_integration(self._db, integration_id)
            if record is None:
                return
            if record.polling_status not in {
                "installation_pending",
                "device_pending",
            }:
                return
            if self._clock.time() >= deadline:
                # Stop the task — but leave the row untouched. A returning
                # user's idempotent /connect re-spawns the loop; the picker
                # endpoint (select_installation) works without it anyway.
                logger.info(
                    "poll loop for %s hit the %ss cap; stopping (row left in %s)",
                    integration_id,
                    _POLL_LOOP_MAX_SECONDS,
                    record.polling_status,
                )
                return
            # Honor GitHub's stored interval verbatim. We tried being
            # cleverer here (forcing a 2s tick during device_pending to
            # cut post-Authorize latency) and got immediately punished:
            # GitHub returns ``slow_down`` when polled faster than the
            # advertised interval, ``_apply_poll_result`` raises the
            # stored interval, and the override left us polling at 2s
            # forever — so the stored interval kept escalating
            # (5 → 30 → 60 → 155s). The latency win is recovered via
            # the /poll-now nudge endpoint the SPA hits on tab-return
            # from the Authorize page.
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
            await self._audit.log(
                AuditEvent(
                    event_type="github_app.token_received",
                    integration_id=integration_id,
                    provider_name="github",
                    status="success",
                )
            )

            github_login: str | None = None
            try:
                user = await client.fetch_user(access_token=result.access_token)
                github_login = user.login
            except Exception as exc:  # noqa: BLE001 — login is a nicety
                logger.warning("fetch_user failed post-connect: %s", exc)

            token_expires_at = (
                self._expires_at_iso(result.expires_in) if result.expires_in else None
            )

            # ADR-0048 — if the legacy /setup callback already bound an
            # installation_id, connect straight away; otherwise discover
            # the installation from the user access token.
            if record.installation_id is not None:
                await self._finalize_connected(
                    integration_id,
                    installation_id=None,
                    github_login=github_login,
                    token_expires_at=token_expires_at,
                )
            else:
                await self._try_resolve_installation(
                    integration_id,
                    client,
                    access_token=result.access_token,
                    github_login=github_login,
                    token_expires_at=token_expires_at,
                    persist_pending=True,
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

    # ------------------------------------------------------------------
    # Installation discovery (ADR-0048)
    # ------------------------------------------------------------------

    def _filter_our_installations(
        self, installations: list[InstallationInfo]
    ) -> list[InstallationInfo]:
        """Keep only installations of *our* App.

        ``/user/installations`` reports installations of every App the
        user has authorized, so the slug filter is what isolates ours.
        """
        return [i for i in installations if i.app_slug == self._app_slug]

    async def _try_resolve_installation(
        self,
        integration_id: str,
        client: GithubAppClientProtocol,
        *,
        access_token: str,
        github_login: str | None,
        token_expires_at: str | None,
        persist_pending: bool,
    ) -> None:
        """Discover the App installation from *access_token* and connect
        when exactly one is found.

        Zero or many installations leave the row in the non-terminal
        ``installation_pending`` state. ``persist_pending=True`` is the
        first resolution right after the device flow — the row must be
        moved into that state and the token recorded.
        ``persist_pending=False`` is a later background re-discovery tick
        where the row is already pending: nothing to write, just retry
        on the next tick.
        """
        try:
            installations = await client.list_installations(
                access_token=access_token
            )
        except Exception:  # noqa: BLE001 — any failure: stay pending, retry
            # logger.exception keeps the stack trace so a genuine bug here
            # (vs. a transient GitHub blip) stays diagnosable.
            logger.exception(
                "installation discovery failed for %s", integration_id
            )
            if persist_pending:
                await gh_repo.record_device_authorized(
                    self._db,
                    integration_id,
                    github_login=github_login,
                    token_expires_at=token_expires_at,
                )
            return

        ours = self._filter_our_installations(installations)
        if len(ours) == 1:
            await self._finalize_connected(
                integration_id,
                installation_id=ours[0].installation_id,
                github_login=github_login,
                token_expires_at=token_expires_at,
            )
        elif persist_pending:
            # Zero (user must install) or many (user must pick) — hold the
            # row in installation_pending with the token stored.
            await gh_repo.record_device_authorized(
                self._db,
                integration_id,
                github_login=github_login,
                token_expires_at=token_expires_at,
            )

    async def _finalize_connected(
        self,
        integration_id: str,
        *,
        installation_id: int | None,
        github_login: str | None,
        token_expires_at: str | None,
    ) -> GithubAppInstallation:
        """Mark the row connected, enable the integration, archive PATs.

        Shared by every connect path: the legacy callback-bound success,
        single-installation discovery, the background discovery tick, and
        the picker. ``installation_id=None`` keeps whatever the ``/setup``
        callback already bound. Returns the now-connected row.
        """
        record = await gh_repo.mark_connected(
            self._db,
            integration_id,
            github_login=github_login,
            token_expires_at=token_expires_at,
            installation_id=installation_id,
        )
        assert record is not None  # the row we just updated
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
        return record

    async def _terminate(
        self,
        integration_id: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        with contextlib.suppress(KeyError):
            await self._vault.delete(integration_id, GITHUB_DEVICE_CODE_KEY)
        # SR-4: cap the persisted error string. Upstream client builders
        # already truncate before raising, but a different caller (or a
        # bare ``str(exc)`` path) might pass an unbounded message — the
        # DB column has no length limit, so do this defensively here too.
        bounded_error = error if error is None else error[:_POLLING_ERROR_MAX_CHARS]
        await gh_repo.update_polling_status(
            self._db, integration_id, status=status, error=bounded_error  # type: ignore[arg-type]
        )

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
