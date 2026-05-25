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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from cliff.api.routes.workspaces import _resolve_repo_env_vars
from cliff.config import settings
from cliff.db import repo_integration
from cliff.db.connection import get_db
from cliff.integrations.github_app import repo as gh_repo
from cliff.integrations.github_app.client import (
    GitHubDeviceFlowClient,
    build_install_url,
    check_repo_push_access,
)
from cliff.integrations.github_app.flow import (
    DeviceFlowOrchestrator,
    InstallationCsrfMismatchError,
    IntegrationAlreadyConnectedError,
)
from cliff.integrations.github_app.models import (
    DeviceFlowConnectResponse,
    DeviceFlowDisconnectResponse,
    DeviceFlowManualSetupRequest,
    DeviceFlowStatusResponse,
    PushAccessDiagnoseResponse,
)
from cliff.models import IntegrationConfigCreate

if TYPE_CHECKING:
    import aiosqlite

    from cliff.integrations.audit import AuditLogger
    from cliff.integrations.github_app.flow import GithubAppClientProtocol
    from cliff.integrations.vault import CredentialVault

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
    """Validate that *value* is a known onboarding/settings path.

    Strips any user-supplied ``#fragment`` before allow-list comparison
    (SR-3 in PR #145 review): a fragment is never meaningful as a
    return-target and could otherwise be reflected back into the SPA's
    ``location.hash``.
    """
    if not value:
        return DEFAULT_RETURN_PATH
    if not value.startswith("/"):
        return DEFAULT_RETURN_PATH
    if "#" in value:
        value = value.split("#", 1)[0] or DEFAULT_RETURN_PATH
    for prefix in _ALLOWED_RETURN_PATHS:
        if value == prefix or value.startswith(prefix + "?"):
            return value
    return DEFAULT_RETURN_PATH


def _require_same_origin(request: Request) -> None:
    """Reject mutating requests that didn't originate from a known UI origin.

    Single-user community edition has no auth layer (per project description).
    On a non-loopback deploy a malicious page in the user's browser could
    trigger e.g. ``POST /disconnect`` against the user's own Cliff via
    cross-site form submission. We block that by requiring the request
    Origin (or, falling back, Referer) to match either the configured
    frontend base URL or the request's own host. SR-1 in PR #145 review.

    /setup is intentionally exempt — GitHub redirects there from
    github.com so an Origin check would always fail. /setup defends
    instead via the cryptographic ``state`` parameter (SR-2).
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin is None:
        # No Origin/Referer means the request didn't come from a browser
        # context (curl, automation, server-to-server). Those aren't a
        # CSRF threat — CSRF requires a victim browser session. Allow.
        return
    allowed = {
        _resolve_frontend_base_url().rstrip("/"),
    }
    if request.url.hostname:
        if request.url.port:
            allowed.add(f"http://{request.url.hostname}:{request.url.port}")
        else:
            allowed.add(f"http://{request.url.hostname}")
    # Compare scheme+host(+port) only — strip path/query/fragment.
    from urllib.parse import urlparse as _urlparse

    parsed = _urlparse(origin)
    candidate = f"{parsed.scheme}://{parsed.netloc}"
    if candidate not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cross-origin request rejected (origin={candidate})",
        )


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
                "Set CLIFF_GITHUB_APP_CLIENT_ID and CLIFF_GITHUB_APP_SLUG, "
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


def _resolve_frontend_base_url() -> str:
    """Pick the right origin for the post-install redirect.

    Priority:
    1. Explicit override via ``CLIFF_FRONTEND_BASE_URL``.
    2. ``CLIFF_STATIC_DIR`` set → backend serves the SPA on the same
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

    _require_same_origin(request)
    async with _connect_lock(request):
        integration_id = await _resolve_or_create_app_integration(db)
        orchestrator = _get_orchestrator(request, db, vault, audit)
        try:
            started = await orchestrator.initiate(integration_id)
        except IntegrationAlreadyConnectedError as exc:
            # SR-1 / F1: refuse to silently nuke an active install. Caller
            # must explicitly /disconnect first.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        install_url=build_install_url(
            settings.github_app_slug, state=started.csrf_state
        ),
    )


async def _register_installation(
    *,
    request: Request,
    db: aiosqlite.Connection,
    state: str,
    installation_id: int,
) -> None:
    """Shared registration path for both ``GET /setup`` and ``POST /setup/manual``.

    Wraps :py:meth:`DeviceFlowOrchestrator.attach_installation` so the
    route layer has one — and only one — way to bind an
    ``installation_id`` to a CSRF state. The GET callback turns the
    :class:`InstallationCsrfMismatchError` into a redirect; the POST
    recovery endpoint turns it into a 400. Either way the underlying
    validation is identical, which is the load-bearing property that
    keeps the recovery flow from being a CSRF-bypass.

    Raises :class:`InstallationCsrfMismatchError` on a state we never
    issued or a replay with a different installation_id (SR-2).
    """
    vault, audit = _require_vault_and_audit(request)
    orchestrator = _get_orchestrator(request, db, vault, audit)
    await orchestrator.attach_installation(
        csrf_state=state, installation_id=installation_id
    )


@router.get("/setup")
async def setup_callback(
    request: Request,
    # SR-5: reject zero/negative IDs early — GitHub installation IDs are
    # always positive. Saves us from binding a row to a nonsense value
    # that GitHub will later refuse anyway.
    installation_id: int = Query(..., gt=0),
    # GitHub sends ``setup_action`` ∈ {"install", "update"}. ``install``
    # is the first time the user installs Cliff on the account;
    # ``update`` fires when they revisit the App page and reconfigure
    # repos. We honour both, but tag the redirect so the SPA can show
    # different copy ("Connected" vs "Configuration updated").
    setup_action: Literal["install", "update"] = Query("install"),
    # ``state`` is OPTIONAL. The onboarding flow's install_url carries
    # a CSRF state so /setup can bind installation_id to the in-flight
    # row. But post-onboarding installs (e.g. the picker's "Install on
    # <org>" link, or a user installing on additional orgs from
    # github.com directly) don't have an in-flight row — there's no
    # state to pass. When state is absent we skip the binding step and
    # just redirect the user to the SPA. The integration was already
    # established via the device-flow token; the new installation_id
    # surfaces via /user/installations on the next picker query.
    state: str | None = Query(None, min_length=8, max_length=128),
    db: aiosqlite.Connection = Depends(get_db),
) -> RedirectResponse:
    _require_app_configured()

    redirect_status = "updated" if setup_action == "update" else "complete"

    if state is None:
        # Post-onboarding install path: no state, no binding, just send
        # the user back to Settings with a success tag so the picker
        # can refresh its installation set.
        return RedirectResponse(
            _frontend_redirect(DEFAULT_RETURN_PATH, status=redirect_status),
            status_code=302,
        )

    return_path = _pop_return_path(request, state)

    try:
        await _register_installation(
            request=request,
            db=db,
            state=state,
            installation_id=installation_id,
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


@router.post("/setup/manual", response_model=DeviceFlowStatusResponse)
async def setup_manual(
    request: Request,
    payload: DeviceFlowManualSetupRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> DeviceFlowStatusResponse:
    """Manual recovery for B33 — accept an ``installation_id`` posted from
    the SPA when the GET callback never fired.

    The shared ``opensec-local-test`` GitHub App's Setup URL is globally
    hardcoded to ``http://localhost:8000/api/integrations/github/setup``
    on github.com. Any Cliff deployment bound to a different host port
    (Docker remap, parallel dev stack, reverse proxy) never receives
    the GET callback. This endpoint lets the user paste the
    ``installation_id`` from the redirect URL they ended up on — Cliff
    then drives the same registration code path as the GET callback,
    *including the CSRF state check* that prevents an attacker who
    tricks the user into pasting a hostile ``installation_id`` from
    binding it.
    """
    _require_app_configured()
    # SR-1 parity with the rest of the mutating routes — block browser-
    # initiated cross-origin POSTs. The GET callback is intentionally
    # exempt (it's a github.com redirect, no Origin); the manual path is
    # a same-origin browser action and gets the full guard.
    _require_same_origin(request)

    # Drain the stashed return-path entry for this state — the SPA
    # already knows where it is (it's calling us from the recovery
    # card), so we just want to keep the in-memory map from leaking
    # this entry. _pop_return_path is safe on unknown states.
    _pop_return_path(request, payload.state)

    try:
        await _register_installation(
            request=request,
            db=db,
            state=payload.state,
            installation_id=payload.installation_id,
        )
    except InstallationCsrfMismatchError as exc:
        # 400 (not redirect) — the SPA shows an inline error on the
        # recovery card. The wording matters: don't echo the state
        # value, since it's user-supplied and may end up in logs.
        raise HTTPException(
            status_code=400,
            detail=(
                "csrf state mismatch — the installation_id was not bound "
                "to a state this Cliff instance issued"
            ),
        ) from exc

    record = await gh_repo.get_by_csrf(db, payload.state)
    assert record is not None  # _register_installation just bound this row
    return DeviceFlowStatusResponse(
        status=record.polling_status,
        user_code=record.user_code,
        expires_at=record.device_code_expires_at,
        installation_id=record.installation_id,
        github_login=record.github_login,
        error=record.polling_error,
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
    Authorize and comes back to Cliff, they shouldn't have to wait
    for the next scheduled tick — the SPA hits this endpoint on the
    visibility-change event so the modal flips to Connected within
    one round-trip instead of up to a minute.
    """
    _require_app_configured()
    _require_same_origin(request)
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


# ---------------------------------------------------------------------------
# Push-access diagnostic (Q01R-W2 / B35c / IMPL-0018)
#
# A thin pass-through over check_repo_push_access that the Settings page's
# <PushAccessBadge> renders on mount. Surfaces the same information the
# executor's 412 preflight would surface — but BEFORE the user clicks
# Approve, so a misconfigured GitHub App is visible at the natural
# "check setup" spot rather than after a 4-minute executor run.
#
# Cached for 5 minutes per (token, repo_url) tuple so re-mounting the
# Settings page doesn't burn GitHub-side rate budget. Refresh via the
# `?refresh=1` query param when the user fixes the App on github.com and
# wants to re-verify without waiting for the TTL.
# ---------------------------------------------------------------------------


# 5 minutes — matches the Risk-section guidance in IMPL-0018. Short enough
# that a real fix lands quickly in the badge; long enough that page
# re-mounts and side-by-side tabs don't burn a GitHub call each.
_DIAGNOSE_CACHE_TTL_SECONDS = 5 * 60


def _parse_owner_repo_from_url(repo_url: str) -> tuple[str, str] | None:
    """Best-effort ``owner/repo`` extraction for github.com HTTPS URLs.

    Mirrors the parser the executor route uses for its push preflight
    (``agent_execution._parse_owner_repo_from_url``). We can't import that
    helper directly without a route-layer cycle, but the rules are simple
    enough — and load-bearing enough — that a duplicated 10-liner is
    cheaper than the refactor. The two MUST stay in lockstep: any URL
    the executor would accept must also be a URL we'll diagnose, and
    vice versa.

    Security: exact ``hostname == "github.com"`` check, not substring/
    endswith, to defeat the CodeQL py/incomplete-url-substring-sanitization
    patterns (``https://attacker.com/github.com/...`` and
    ``https://github.com.attacker.com/...``).
    """
    if not isinstance(repo_url, str) or not repo_url:
        return None
    try:
        parsed = urlparse(repo_url)
    except ValueError:
        return None
    if parsed.scheme not in ("https", "http"):
        return None
    if parsed.hostname != "github.com":
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return None
    return owner, name


def _diagnose_cache(request: Request) -> dict[str, tuple[PushAccessDiagnoseResponse, float]]:
    """Process-local cache keyed by repo URL.

    Why repo URL and not just "the GitHub integration": the user can
    disconnect and reconnect pointing at a different org/repo. If we
    keyed solely on integration ID (or didn't key at all), the badge
    would echo the previous repo's verdict for up to 5 minutes after a
    reconnect — exactly the failure mode the task brief calls out.
    """
    state = request.app.state
    existing = getattr(state, "github_diagnose_cache", None)
    if existing is None:
        existing = {}
        state.github_diagnose_cache = existing
    return existing


def _evict_expired_diagnose_entries(
    cache: dict[str, tuple[PushAccessDiagnoseResponse, float]],
) -> None:
    now = time.time()
    fresh = {k: v for k, v in cache.items() if v[1] > now}
    if len(fresh) != len(cache):
        cache.clear()
        cache.update(fresh)


@router.get(
    "/diagnose",
    response_model=PushAccessDiagnoseResponse,
)
async def diagnose_push_access(
    request: Request,
    refresh: int = Query(default=0, ge=0, le=1),
    db: aiosqlite.Connection = Depends(get_db),
) -> PushAccessDiagnoseResponse:
    """Verify push access for the currently-configured GitHub repo.

    Resolution path (same as the executor preflight, so the badge and
    the 412 page agree by construction):

    1. ``_resolve_repo_env_vars`` reads the GitHub integration row +
       vault token. Returns an empty dict if no enabled GitHub
       integration exists.
    2. Parse ``owner/repo`` out of ``CLIFF_REPO_URL``. A non-GitHub
       remote is treated as "nothing to diagnose" and falls through to
       404 — the badge is GitHub-App-specific.
    3. Call :func:`check_repo_push_access` with the stored token. That
       helper already returns UI-safe ``reason`` strings; we pass the
       result through untouched.

    The result is cached per repo URL for 5 minutes. ``?refresh=1``
    forces a fresh GitHub call.
    """
    # No app-config gate here on purpose: even if CLIFF_GITHUB_APP_CLIENT_ID
    # is unset, a PAT-based integration still has a token + repo URL we
    # can diagnose. The check itself doesn't care about App vs PAT.
    env_vars = await _resolve_repo_env_vars(request, db)
    token = env_vars.get("GH_TOKEN")
    repo_url = env_vars.get("CLIFF_REPO_URL")

    if not token or not repo_url:
        # No GitHub configured at all → the badge renders nothing. We
        # deliberately don't surface a red error here: the Settings page
        # already has a "Connect GitHub" CTA for this state, and a
        # scary push-access banner on a not-yet-connected install is
        # confusing.
        raise HTTPException(
            status_code=404, detail="GitHub integration not configured"
        )

    owner_repo = _parse_owner_repo_from_url(repo_url)
    if owner_repo is None:
        # Repo URL exists but isn't a github.com URL (or is malformed).
        # The executor preflight skips this case for the same reason —
        # we can't diagnose what we can't address.
        raise HTTPException(
            status_code=404,
            detail="GitHub integration is not pointed at a github.com repo",
        )

    cache = _diagnose_cache(request)
    _evict_expired_diagnose_entries(cache)

    if not refresh:
        cached = cache.get(repo_url)
        if cached is not None:
            response, _expires_at = cached
            return response

    owner, repo = owner_repo
    access = await check_repo_push_access(token=token, owner=owner, repo=repo)

    response = PushAccessDiagnoseResponse(
        can_push=access.can_push,
        reason=access.reason,
        repo_url=repo_url,
        checked_at=datetime.now(UTC).isoformat(),
    )
    cache[repo_url] = (response, time.time() + _DIAGNOSE_CACHE_TTL_SECONDS)
    return response


@router.post("/disconnect", response_model=DeviceFlowDisconnectResponse)
async def disconnect(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> DeviceFlowDisconnectResponse:
    # Deliberately NOT gated on _require_app_configured: if the operator
    # unsets CLIFF_GITHUB_APP_CLIENT_ID after a user has connected, we
    # still want the cleanup path to work so they aren't stranded with a
    # non-refreshable token in the vault.
    _require_same_origin(request)
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
    from cliff.db import connection as db_connection
    from cliff.main import app as fastapi_app

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
