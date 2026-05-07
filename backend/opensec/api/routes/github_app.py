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

import logging
from typing import TYPE_CHECKING
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

GITHUB_PROVIDER = "github"
GITHUB_ADAPTER = "finding_source"
GITHUB_MANUAL_REVOKE_URL = "https://github.com/settings/applications"


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
    return (
        f"https://github.com/apps/{settings.github_app_slug}"
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


def _frontend_redirect(*, status: str, **extra: str) -> str:
    """Build the post-callback redirect back to the SPA Integrations page."""
    params = {"github_setup": status, **extra}
    return f"{_resolve_frontend_base_url()}/settings/integrations?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Singleton-integration helper
# ---------------------------------------------------------------------------


async def _resolve_or_create_app_integration(db: aiosqlite.Connection) -> str:
    """Find the singleton App-onboarded github integration, creating one if needed.

    The PAT integration (if any) lives as a separate row and is left
    untouched until a successful App connect archives it via
    DeviceFlowOrchestrator.
    """
    existing = await db.execute(
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
    row = await existing.fetchone()
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
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowConnectResponse:
    _require_app_configured()
    vault, audit = _require_vault_and_audit(request)

    integration_id = await _resolve_or_create_app_integration(db)
    orchestrator = _get_orchestrator(request, db, vault, audit)
    started = await orchestrator.initiate(integration_id)
    # Spawn (or re-attach to) the background polling loop so the access
    # token is fetched as soon as the user authorizes on github.com —
    # without this the /status endpoint would never advance off
    # device_pending. Idempotent.
    await orchestrator.start(integration_id)

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
    setup_action: str = Query("install"),  # noqa: ARG001 — accepted from GitHub
    db: aiosqlite.Connection = Depends(get_db),
) -> RedirectResponse:
    _require_app_configured()
    vault, audit = _require_vault_and_audit(request)
    orchestrator = _get_orchestrator(request, db, vault, audit)
    try:
        await orchestrator.attach_installation(
            csrf_state=state, installation_id=installation_id
        )
    except InstallationCsrfMismatchError:
        return RedirectResponse(
            _frontend_redirect(status="error", reason="csrf"),
            status_code=302,
        )
    return RedirectResponse(
        _frontend_redirect(status="complete"), status_code=302
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


@router.post("/disconnect", response_model=DeviceFlowDisconnectResponse)
async def disconnect(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowDisconnectResponse:
    vault, audit = _require_vault_and_audit(request)

    cursor = await db.execute(
        "SELECT integration_id FROM github_app_installation LIMIT 1"
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
