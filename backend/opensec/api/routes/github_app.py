"""GitHub App + Device Flow onboarding routes (ADR-0035, IMPL-0010).

Mounted at ``/api/integrations/github``. Four endpoints:

- ``POST /connect``    — kick off (or resume) the device flow.
- ``GET  /setup``      — landing page after Install on github.com.
- ``GET  /status``     — frontend polls this every ~2s while modal open.
- ``POST /disconnect`` — drop credentials + installation row locally.

The user access token issued by the device flow lands in the existing
credential vault under the same key the MCP Gateway already substitutes,
so workspaces transparently keep working without any agent-side change.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from opensec.config import settings
from opensec.db import repo_integration
from opensec.db.connection import get_db
from opensec.integrations.github_app import repo as gh_repo
from opensec.integrations.github_app.client import GitHubDeviceFlowClient
from opensec.integrations.github_app.flow import (
    DeviceFlowOrchestrator,
    InstallationCsrfMismatchError,
)
from opensec.integrations.github_app.models import (
    DeviceFlowConnectResponse,
    DeviceFlowDisconnectResponse,
    DeviceFlowStatusResponse,
)
from opensec.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite

    from opensec.integrations.audit import AuditLogger
    from opensec.integrations.github_app.flow import GithubAppClientProtocol
    from opensec.integrations.vault import CredentialVault

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/github", tags=["github-app"])

# These MUST match the constants used by routes/onboarding.py
# (GITHUB_ADAPTER_TYPE, GITHUB_PROVIDER_NAME). Every downstream consumer
# (_engine_dep.py, workspaces.py, executor.py, connection_tester.py)
# looks up the GitHub integration by these exact values; a mismatch
# would silently make the assessment + workspace-clone paths run
# unauthenticated even though the device flow succeeded.
GITHUB_PROVIDER = "GitHub"
GITHUB_ADAPTER = "github"
GITHUB_MANUAL_REVOKE_URL = "https://github.com/settings/applications"
DEFAULT_RETURN_PATH = "/settings"

# Allow-list for return_to paths we'll redirect to after a successful App
# install. Any value POSTed to /connect must match one of these prefixes
# verbatim — otherwise it's silently dropped and the default is used.
# Prevents an attacker from coercing the redirect to an arbitrary site.
_ALLOWED_RETURN_PATHS: tuple[str, ...] = (
    "/settings",
    "/onboarding/connect",
)


def _sanitize_return_path(value: str | None) -> str:
    """Validate that *value* is a known onboarding/settings path."""
    if not value:
        return DEFAULT_RETURN_PATH
    if not value.startswith("/"):
        return DEFAULT_RETURN_PATH
    for prefix in _ALLOWED_RETURN_PATHS:
        if value == prefix or value.startswith(prefix + "?") or value.startswith(prefix + "#"):
            return value
    return DEFAULT_RETURN_PATH


# In-memory map csrf_state -> (return_path, expires_at). Process-lifetime.
# Acceptable because the device-flow window is at most 15 minutes; if
# the process restarts mid-flow the user lands on the default path,
# which is still a valid recovery point. Keeps the schema migration-free.
#
# Each entry is bounded by ``RETURN_PATH_TTL_SECONDS`` so an abandoned
# /connect (user never installs) doesn't leak memory under repeated
# clicks. ``MAX_RETURN_PATHS`` is a hard cap on entry count as a
# secondary defense against pathological abuse.
RETURN_PATH_TTL_SECONDS = 30 * 60  # comfortably above the 15-minute device-code window
MAX_RETURN_PATHS = 256


def _return_paths(request: Request) -> dict[str, tuple[str, float]]:
    state = request.app.state
    existing = getattr(state, "github_app_return_paths", None)
    if existing is None:
        existing = {}
        state.github_app_return_paths = existing
    return existing


def _evict_expired_return_paths(paths: dict[str, tuple[str, float]]) -> None:
    """Drop entries past their TTL. Called on every read/write so the
    map self-heals without a separate sweeper task."""
    now = time.time()
    fresh = {k: v for k, v in paths.items() if v[1] > now}
    if len(fresh) != len(paths):
        paths.clear()
        paths.update(fresh)


def _stash_return_path(request: Request, csrf_state: str, path: str) -> None:
    paths = _return_paths(request)
    _evict_expired_return_paths(paths)
    # Hard cap (defense in depth): drop the oldest entries if we're at
    # the cap. Wouldn't trigger under normal use but stops a malicious
    # client from blowing memory by spamming /connect.
    if len(paths) >= MAX_RETURN_PATHS:
        # Drop the oldest-expiring entries to make room.
        ordered = sorted(paths, key=lambda k: paths[k][1])
        drop_count = max(1, len(paths) - MAX_RETURN_PATHS + 1)
        for key in ordered[:drop_count]:
            paths.pop(key, None)
    paths[csrf_state] = (path, time.time() + RETURN_PATH_TTL_SECONDS)


def _pop_return_path(request: Request, csrf_state: str) -> str:
    paths = _return_paths(request)
    _evict_expired_return_paths(paths)
    entry = paths.pop(csrf_state, None)
    if entry is None:
        return DEFAULT_RETURN_PATH
    path, _ = entry
    return path


# ---------------------------------------------------------------------------
# Construction helpers (overridable in tests)
# ---------------------------------------------------------------------------


def _build_github_client() -> GithubAppClientProtocol:
    """Build a real GitHubDeviceFlowClient. Tests override this via patch."""
    return GitHubDeviceFlowClient(client_id=settings.github_app_client_id)


def _build_orchestrator(
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
) -> DeviceFlowOrchestrator:
    return DeviceFlowOrchestrator(
        db=db,
        vault=vault,
        audit=audit,
        client_factory=_build_github_client,
        app_slug=settings.github_app_slug,
        client_id=settings.github_app_client_id,
    )


def _get_orchestrator(
    request: Request,
    db: aiosqlite.Connection,
    vault: CredentialVault,
    audit: AuditLogger,
) -> DeviceFlowOrchestrator:
    """Process-singleton orchestrator stored on ``app.state``.

    Why a singleton: the orchestrator owns an in-memory map of running
    polling tasks keyed by integration_id. If we built a fresh
    orchestrator per request, ``start()`` would spawn a new task on
    every /connect (orphaning the previous one) and ``disconnect``
    would never find a task to cancel. One instance per process keeps
    the lifecycle clean — and lets the FakeClient transport survive
    across requests in tests too.
    """
    existing = getattr(request.app.state, "github_app_orchestrator", None)
    if existing is not None:
        return existing
    orchestrator = _build_orchestrator(db, vault, audit)
    request.app.state.github_app_orchestrator = orchestrator
    return orchestrator


def _require_app_configured() -> None:
    if not settings.github_app_client_id or not settings.github_app_slug:
        raise HTTPException(
            status_code=503,
            detail=(
                "GitHub App onboarding is not configured on this instance. "
                "Set OPENSEC_GITHUB_APP_CLIENT_ID and OPENSEC_GITHUB_APP_SLUG, "
                "or fall back to the personal access token form."
            ),
        )


def _require_vault_and_audit(request: Request) -> tuple[CredentialVault, AuditLogger]:
    vault = getattr(request.app.state, "vault", None)
    audit = getattr(request.app.state, "audit_logger", None)
    if vault is None or audit is None:
        raise HTTPException(
            status_code=503,
            detail="Credential vault or audit logger unavailable.",
        )
    return vault, audit


def _install_url(csrf_state: str) -> str:
    # Quote the slug too — the value comes from env (trusted by intent),
    # but defending against a typo with ``/`` or ``?`` in it is free.
    slug = quote(settings.github_app_slug, safe="")
    return (
        f"https://github.com/apps/{slug}"
        f"/installations/new?state={quote(csrf_state, safe='')}"
    )


def _resolve_frontend_base_url() -> str:
    """Pick the right origin for the post-install redirect.

    Priority:
    1. Explicit override via ``OPENSEC_FRONTEND_BASE_URL``.
    2. ``OPENSEC_STATIC_DIR`` set → backend serves the SPA on the same
       origin as the API → use ``base_url``.
    3. Neither set → assume Vite dev convention on ``:5173``.
    """
    if settings.frontend_base_url:
        return settings.frontend_base_url.rstrip("/")
    if settings.static_dir:
        return settings.base_url.rstrip("/")
    return "http://localhost:5173"


def _frontend_redirect(return_path: str, *, status: str, **extra: str) -> str:
    """Build the post-callback redirect back to the SPA.

    *return_path* is a sanitized SPA-relative path (e.g. ``/settings``
    or ``/onboarding/connect``). Anchors and query params on the path
    are preserved when present; otherwise we add the section anchor
    for /settings so the browser scrolls to the integrations section.
    The ``?github_setup=...`` query param is what
    ``useGithubAppResumeOnReturn`` reads on mount to re-open the modal.
    """
    params = {"github_setup": status, **extra}
    base = _resolve_frontend_base_url()

    # Split off any pre-existing query/hash so we layer ours on top
    # without colliding.
    path_only = return_path
    existing_hash = ""
    if "#" in path_only:
        path_only, existing_hash = path_only.split("#", 1)
        existing_hash = f"#{existing_hash}"
    if "?" in path_only:
        # Drop the user-supplied query — our params are the only ones
        # the resume hook cares about.
        path_only = path_only.split("?", 1)[0]

    # Default scroll anchor for the settings page (where the
    # integrations section lives). Onboarding pages keep no anchor.
    if not existing_hash and path_only == "/settings":
        existing_hash = "#integrations"

    return f"{base}{path_only}?{urlencode(params)}{existing_hash}"


# ---------------------------------------------------------------------------
# Singleton-integration helper
# ---------------------------------------------------------------------------


def _connect_lock(request: Request) -> asyncio.Lock:
    """Process-singleton lock guarding _resolve_or_create_app_integration.

    Two concurrent /connect calls (rapid double-click) would otherwise
    both miss the SELECT-then-INSERT check and create duplicate
    integration_config rows for ``provider_name='GitHub'``. Single-user
    mode is single-process, so an asyncio.Lock is sufficient. (For
    SaaS multi-user we'd need a DB-level UNIQUE partial index — out
    of scope for this PR.)
    """
    state = request.app.state
    existing = getattr(state, "github_app_connect_lock", None)
    if existing is None:
        existing = asyncio.Lock()
        state.github_app_connect_lock = existing
    return existing


async def _resolve_or_create_app_integration(db: aiosqlite.Connection) -> str:
    """Find the singleton App-onboarded github integration, creating one if needed.

    The PAT integration (if any) lives as a separate row and is left
    untouched until a successful App connect archives it via
    DeviceFlowOrchestrator.

    Caller must hold ``_connect_lock(request)`` to make the
    SELECT-then-INSERT atomic across concurrent /connect calls.
    """
    cursor = await db.execute(
        """
        SELECT integration_config.id
        FROM integration_config
        INNER JOIN github_app_installation
                ON github_app_installation.integration_id = integration_config.id
        WHERE integration_config.provider_name = ?
        LIMIT 1
        """,
        (GITHUB_PROVIDER,),
    )
    row = await cursor.fetchone()
    if row is not None:
        return row["id"]

    integ = await repo_integration.create_integration(
        db,
        IntegrationConfigCreate(
            adapter_type=GITHUB_ADAPTER,
            provider_name=GITHUB_PROVIDER,
            enabled=False,
            config=None,
            action_tier=0,
        ),
    )
    return integ.id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/connect", response_model=DeviceFlowConnectResponse)
async def connect(
    request: Request,
    return_to: str | None = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
) -> DeviceFlowConnectResponse:
    _require_app_configured()
    vault, audit = _require_vault_and_audit(request)

    async with _connect_lock(request):
        integration_id = await _resolve_or_create_app_integration(db)
        orchestrator = _get_orchestrator(request, db, vault, audit)
        started = await orchestrator.initiate(integration_id)
    # Spawn (or re-attach to) the background polling loop so the access
    # token is fetched as soon as the user authorizes on github.com —
    # without this the /status endpoint would never advance off
    # device_pending. Idempotent.
    await orchestrator.start(integration_id)

    # Stash a sanitized return path keyed by CSRF state. The setup
    # callback reads it post-install and redirects there instead of the
    # default /settings, so the App flow seamlessly returns the user to
    # whichever page (onboarding, settings) started the flow.
    _stash_return_path(request, started.csrf_state, _sanitize_return_path(return_to))

    return DeviceFlowConnectResponse(
        user_code=started.user_code,
        verification_uri=started.verification_uri,
        expires_in=started.expires_in,
        interval=started.interval,
        install_url=_install_url(started.csrf_state),
    )


@router.get("/setup")
async def setup_callback(
    request: Request,
    state: str = Query(...),
    installation_id: int = Query(...),
    # GitHub sends ``setup_action`` ∈ {"install", "update"}. ``install``
    # is the first time the user installs OpenSec on the account;
    # ``update`` fires when they revisit the App page and reconfigure
    # repos. We honour both, but tag the redirect so the SPA can show
    # different copy ("Connected" vs "Configuration updated").
    setup_action: Literal["install", "update"] = Query("install"),
    db: aiosqlite.Connection = Depends(get_db),
) -> RedirectResponse:
    _require_app_configured()
    vault, audit = _require_vault_and_audit(request)
    orchestrator = _get_orchestrator(request, db, vault, audit)
    return_path = _pop_return_path(request, state)

    redirect_status = "updated" if setup_action == "update" else "complete"

    try:
        await orchestrator.attach_installation(
            csrf_state=state, installation_id=installation_id
        )
    except InstallationCsrfMismatchError:
        return RedirectResponse(
            _frontend_redirect(return_path, status="error", reason="csrf"),
            status_code=302,
        )
    return RedirectResponse(
        _frontend_redirect(return_path, status=redirect_status),
        status_code=302,
    )


@router.get("/status", response_model=DeviceFlowStatusResponse)
async def status(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowStatusResponse:
    _require_app_configured()
    # Find any github integration that has an installation row (in-flight or
    # connected). If none exists, 404 — caller should POST /connect.
    cursor = await db.execute(
        """
        SELECT integration_id FROM github_app_installation
        ORDER BY updated_at DESC LIMIT 1
        """,
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No GitHub App flow in progress")

    integration_id = row["integration_id"]
    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    return DeviceFlowStatusResponse(
        status=record.polling_status,
        user_code=record.user_code,
        expires_at=record.device_code_expires_at,
        installation_id=record.installation_id,
        github_login=record.github_login,
        error=record.polling_error,
    )


@router.post("/poll-now", response_model=DeviceFlowStatusResponse)
async def poll_now(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowStatusResponse:
    """Force an immediate poll tick + return the resulting status.

    The background polling loop honors GitHub's stored interval (5s
    minimum, often higher after a ``slow_down``). When the user clicks
    Authorize and comes back to OpenSec, they shouldn't have to wait
    for the next scheduled tick — the SPA hits this endpoint on the
    visibility-change event so the modal flips to Connected within
    one round-trip instead of up to a minute.
    """
    _require_app_configured()
    vault, audit = _require_vault_and_audit(request)

    cursor = await db.execute(
        """
        SELECT integration_id FROM github_app_installation
        ORDER BY updated_at DESC LIMIT 1
        """
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No GitHub App flow in progress")

    integration_id = row["integration_id"]
    orchestrator = _get_orchestrator(request, db, vault, audit)
    # Run a single poll step out-of-band. Idempotent on terminal rows.
    await orchestrator.run_poll_step(integration_id)

    record = await gh_repo.get_for_integration(db, integration_id)
    assert record is not None
    return DeviceFlowStatusResponse(
        status=record.polling_status,
        user_code=record.user_code,
        expires_at=record.device_code_expires_at,
        installation_id=record.installation_id,
        github_login=record.github_login,
        error=record.polling_error,
    )


@router.post("/disconnect", response_model=DeviceFlowDisconnectResponse)
async def disconnect(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowDisconnectResponse:
    # Deliberately NOT gated on _require_app_configured: if the operator
    # unsets OPENSEC_GITHUB_APP_CLIENT_ID after a user has connected, we
    # still want the cleanup path to work so they aren't stranded with a
    # non-refreshable token in the vault.
    vault, audit = _require_vault_and_audit(request)

    # Deterministic ordering: prefer the most-recently-connected row, then
    # most-recently-touched. With the singleton invariant only one row
    # exists in single-user mode; the ordering is defense in depth for
    # forward-compatibility with multi-install SaaS.
    cursor = await db.execute(
        """
        SELECT integration_id FROM github_app_installation
        ORDER BY connected_at DESC, updated_at DESC
        LIMIT 1
        """
    )
    row = await cursor.fetchone()
    if row is not None:
        orchestrator = _get_orchestrator(request, db, vault, audit)
        await orchestrator.disconnect(row["integration_id"])

    return DeviceFlowDisconnectResponse(
        manual_revoke_url=GITHUB_MANUAL_REVOKE_URL,
    )


# ---------------------------------------------------------------------------
# Test seam — drives a single polling tick deterministically
# ---------------------------------------------------------------------------


async def _tick_poll_for_test() -> None:
    """Run one poll step on every in-flight installation.

    Used by route tests to exercise transitions without spinning up the
    background polling task. Production code uses the orchestrator's
    ``start()`` task instead.
    """
    from opensec.db import connection as db_connection
    from opensec.main import app as fastapi_app

    db = db_connection._db
    if db is None:
        return
    vault = getattr(fastapi_app.state, "vault", None)
    audit = getattr(fastapi_app.state, "audit_logger", None)
    if vault is None or audit is None:
        return

    cursor = await db.execute(
        "SELECT integration_id FROM github_app_installation"
    )
    for row in await cursor.fetchall():
        orchestrator = getattr(fastapi_app.state, "github_app_orchestrator", None)
        if orchestrator is None:
            orchestrator = _build_orchestrator(db, vault, audit)
            fastapi_app.state.github_app_orchestrator = orchestrator
        await orchestrator.run_poll_step(row["integration_id"])
