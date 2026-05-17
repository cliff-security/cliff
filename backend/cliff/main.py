"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cliff.agents.executor import AgentExecutor
from cliff.agents.template_engine import AgentTemplateEngine
from cliff.ai import catalog as ai_catalog
from cliff.api.routes import (
    agent_execution,
    agent_runs,
    ai_integrations,
    assessment,
    audit,
    chat,
    completion,
    dashboard,
    findings,
    github_app,
    health,
    messages,
    onboarding,
    posture,
    seed,
    sessions,
    sidebar,
    version,
    workspaces,
)
from cliff.api.routes import (
    config as config_routes,
)
from cliff.api.routes import (
    settings as settings_routes,
)
from cliff.config import settings
from cliff.db import connection as db_connection
from cliff.db.connection import close_db, init_db
from cliff.engine.client import opencode_client
from cliff.engine.config_manager import config_manager
from cliff.engine.pool import WorkspaceProcessPool
from cliff.engine.process import opencode_process
from cliff.integrations.audit import AuditLogger
from cliff.integrations.gateway import MCPConfigResolver
from cliff.integrations.ingest_worker import ingest_worker_loop
from cliff.integrations.vault import CredentialKeyError, CredentialVault
from cliff.workspace.context_builder import WorkspaceContextBuilder
from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _init_vault(app: FastAPI, db: object) -> None:
    """Construct the credential vault and attach it to ``app.state.vault``.

    Vault init is non-fatal: a misconfigured or missing key shouldn't keep the
    rest of the app from starting (health, findings, etc. still work). But the
    failure mode MUST be visible: previously a bare ``except Exception``
    swallowed every error — including key-format problems — under the same
    "set CLIFF_CREDENTIAL_KEY to enable" warning, even when the env var was
    set. Operators then chased a non-existent missing-key bug while every
    credential-protected route silently 503'd (B32).

    Now ``CredentialKeyError`` (a normal, user-fixable config issue) logs at
    WARNING with the actual reason, and any other ``Exception`` is logged at
    WARNING with ``exc_info=True`` so the traceback reaches the operator.
    """
    try:
        app.state.vault = CredentialVault(db)
        logger.info("Credential vault initialized")
    except CredentialKeyError as exc:
        logger.warning("Credential vault not configured: %s", exc)
    except Exception:
        logger.warning("Credential vault failed to initialize", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start OpenCode on startup, stop on shutdown."""
    logger.info("Starting Cliff...")
    # Surface any active AI model override at boot so operators see them
    # in stdout/stderr (ADR-0036 — performance may vary if a non-default
    # model is in use).
    ai_catalog.log_override_warnings_once()
    # Initialize persistence layer.
    data_dir = settings.resolve_data_dir()
    # macOS Spotlight guard (EF-B15). Empty marker file tells mds_stores
    # to skip this whole tree — Spotlight indexing of per-workspace
    # node_modules was pinning load average ~17 under concurrent
    # workspaces. Harmless on Linux (just an unused dot-file).
    spotlight_marker = data_dir / ".metadata_never_index"
    if not spotlight_marker.exists():
        spotlight_marker.touch()
    db_path = data_dir / "cliff.db"
    first_run = not db_path.exists()
    if first_run:
        logger.info("First run detected — no existing database at %s", db_path)
    else:
        logger.info("Existing database found at %s", db_path)
    await init_db(db_path)

    # Reconcile assessments orphaned by the previous process exit. Background
    # workers are in-memory asyncio tasks; any ``pending``/``running`` row at
    # boot is provably orphaned (the worker that owned it died with the
    # previous process). Without this, a row stuck in ``pending``/``running``
    # leaves the dashboard rendering ``RunningDashboard`` with a permanently
    # disabled "Assessment running" button.
    if db_connection._db is not None:
        from cliff.db.dao.assessment import reconcile_orphaned_assessments
        from cliff.db.repo_agent_run import reconcile_orphaned_agent_runs

        reconciled = await reconcile_orphaned_assessments(db_connection._db)
        if reconciled:
            logger.info(
                "Reconciled %d orphaned assessment row(s) to 'failed' on startup",
                reconciled,
            )

        # Same recovery for agent_runs. Without this, a uvicorn reload
        # mid-execution leaves rows stuck at status='running', the
        # derivation reports stage='generating'/'planning' forever, and
        # the sidebar shows a permanent "Thinking…" the user can't escape.
        reconciled_runs = await reconcile_orphaned_agent_runs(db_connection._db)
        if reconciled_runs:
            logger.info(
                "Reconciled %d orphaned agent_run row(s) to 'failed' on startup",
                reconciled_runs,
            )

    # Demo mode: seed sample findings on startup
    if settings.demo and db_connection._db is not None:
        from cliff.api.routes.seed import DEMO_FINDINGS
        from cliff.db.repo_finding import create_finding, list_findings
        from cliff.models import FindingCreate

        existing = await list_findings(db_connection._db, limit=1)
        if not existing:
            logger.info("Demo mode: seeding %d sample findings", len(DEMO_FINDINGS))
            for data in DEMO_FINDINGS:
                await create_finding(db_connection._db, FindingCreate(**data))
            logger.info("Demo mode: seeding complete")
        else:
            logger.info("Demo mode: findings already exist, skipping seed")

    # Audit logger (non-blocking, queue-based)
    if db_connection._db is not None:
        audit_logger = AuditLogger(db_connection._db)
        await audit_logger.start()
        app.state.audit_logger = audit_logger
    else:
        app.state.audit_logger = None

    # Credential vault (non-fatal if key not configured)
    app.state.vault = None
    if db_connection._db is not None:
        _init_vault(app, db_connection._db)

    # Best-effort one-shot migration: lift any legacy api_key:*
    # app_setting into the new ai_integration table so users coming
    # from the paste flow land on a unified state without re-pasting.
    # Must run BEFORE the env-cache warm so the new row is visible.
    if app.state.vault is not None and db_connection._db is not None:
        from cliff.ai.legacy_migration import migrate_legacy_api_keys_once
        from cliff.ai.service import AIIntegrationService

        await migrate_legacy_api_keys_once(
            db_connection._db,
            AIIntegrationService(
                db_connection._db,
                app.state.vault,
                audit_logger=app.state.audit_logger,
            ),
        )

    # IMPL-0011 Phase F2 + simplify pass: the env injected at every
    # workspace spawn lives on app.state as a cached dict. The
    # resolver returns the cache; the key-change hook (below)
    # refreshes it on every connect/disconnect. Avoids a DB query +
    # vault decrypt on every workspace spawn.
    app.state.ai_env_cache = {}
    app.state.ai_model_cache = None
    # Whether the resolved AI credential actually authenticates. A present,
    # decryptable credential is not the same as a working one — a revoked or
    # wrong key resolves into the workspace env fine and only 401s at
    # agent-run time. ``/health`` and ``cliff status`` gate readiness on
    # this so ``ready: true`` means agents will genuinely run. (Q01-B02.)
    app.state.ai_provider_credential_ok = False

    async def _refresh_ai_env_cache(*, verify: bool = True) -> None:
        """Refresh ``app.state`` AI caches.

        ``verify=False`` skips the upstream credential probe so the
        on-key-change hook (which runs after every save) doesn't block
        the mutation on a second auth round-trip — the BYOK route's own
        validator just confirmed the key works, and a re-run would
        re-issue the same upstream call. Boot keeps ``verify=True``.
        """
        from cliff.ai.service import AIIntegrationService

        vault = app.state.vault
        db = db_connection._db
        if vault is None or db is None:
            app.state.ai_env_cache = {}
            app.state.ai_model_cache = None
            app.state.ai_provider_credential_ok = False
            return
        service = AIIntegrationService(
            db, vault, audit_logger=app.state.audit_logger
        )
        try:
            app.state.ai_env_cache = await service.resolve_env_for_workspace()
            app.state.ai_model_cache = (
                await service.resolve_model_for_workspace()
            )
        except Exception:
            logger.warning(
                "AI integration env refresh failed", exc_info=True
            )
            app.state.ai_env_cache = {}
            app.state.ai_model_cache = None
            app.state.ai_provider_credential_ok = False
            return

        if not app.state.ai_env_cache:
            app.state.ai_provider_credential_ok = False
            return

        if not verify:
            # Trust the caller — the BYOK / autodetect-adopt routes
            # validated the key before invoking the save path, so a
            # second probe here would just duplicate that call.
            app.state.ai_provider_credential_ok = True
            return

        # Boot path: live-probe the resolved credential so readiness reflects
        # "this key authenticates", not just "a key is present" (Q01-B02).
        # Only a definitive auth rejection (401/403 → ``auth_failed``) flips
        # readiness off; network blips, rate limits and billing errors leave
        # the prior readiness value untouched so the signal doesn't flap on
        # a transient probe (L6).
        prior_ok = getattr(app.state, "ai_provider_credential_ok", False)
        try:
            verdict = await service.verify_active_credential()
        except Exception:
            logger.warning(
                "AI credential verification raised (likely transient); "
                "keeping prior readiness=%s",
                prior_ok,
                exc_info=True,
            )
            app.state.ai_provider_credential_ok = prior_ok
            return
        app.state.ai_provider_credential_ok = (
            verdict is not None and verdict.error_code != "auth_failed"
        )

    # Warm the cache once at boot so the very first workspace spawn
    # doesn't pay the DB + decrypt round-trip on the critical path,
    # AND so the singleton OpenCode (started just below) inherits the
    # current AI provider key from boot zero rather than waiting for
    # the first connect / disconnect hook.
    #
    # Skip the live-probe on the boot path (M5): the upstream HTTPS
    # round-trip would block ``lifespan`` for up to 5s, hanging the
    # first post-Docker-restart request. The probe runs as a background
    # task so /healthz answers immediately; readiness flips when it
    # completes.
    await _refresh_ai_env_cache(verify=False)
    asyncio.create_task(_refresh_ai_env_cache(verify=True))

    async def _ai_env_resolver() -> dict[str, str]:
        return dict(app.state.ai_env_cache)

    async def _ai_model_resolver() -> str | None:
        # The OpenCode model id for the active AI provider. The pool writes
        # it into each workspace's opencode.json at spawn time so OpenCode
        # routes calls through the same provider whose key was injected.
        return app.state.ai_model_cache

    # Start AI engine (non-fatal if unavailable). Seed the singleton
    # with the current AI provider env BEFORE start() so the very
    # first /api/settings/providers/test or /chat call hits a process
    # that already authenticates against OpenRouter (or whatever
    # provider is active).
    opencode_process.set_extra_env(app.state.ai_env_cache)
    try:
        await opencode_process.start()
        # Push the active AI integration's key into OpenCode's auth.json.
        # OpenCode 1.3.x consults auth.json in preference to env vars on
        # the outbound request, so users who connected *before* the
        # auth.json sync was added need this reconcile step at startup.
        if app.state.vault is not None and db_connection._db is not None:
            try:
                from cliff.ai.service import AIIntegrationService

                await AIIntegrationService(
                    db_connection._db,
                    app.state.vault,
                    audit_logger=app.state.audit_logger,
                ).sync_to_opencode()
            except Exception:
                logger.warning(
                    "Could not sync AI integration to OpenCode auth.json"
                )
        # Restore stored API keys and reconcile model config (legacy
        # paste-flow path — kept for back-compat with the OpenCode
        # /auth/keys mechanism).
        try:
            if db_connection._db is not None:
                await config_manager.reconcile_model(db_connection._db)
                await config_manager.restore_keys_to_engine(db_connection._db)
        except Exception:
            logger.warning("Could not restore settings to OpenCode engine")
    except Exception:
        logger.exception("Failed to start OpenCode — app will run but engine is unavailable")

    # MCP config resolver (requires vault)
    mcp_resolver = None
    if app.state.vault is not None:
        mcp_resolver = MCPConfigResolver(app.state.vault, app.state.audit_logger)
        logger.info("MCP config resolver initialized")

    # Layer 2: Context builder (workspace directory + agent templates + MCP resolver)
    workspaces_base = settings.resolve_data_dir() / "workspaces"
    dir_manager = WorkspaceDirManager(base_dir=workspaces_base)
    template_engine = AgentTemplateEngine()
    context_builder = WorkspaceContextBuilder(
        dir_manager, template_engine, mcp_resolver=mcp_resolver
    )
    app.state.context_builder = context_builder

    # Layer 3: Per-workspace process pool, reading from the warm cache.
    pool = WorkspaceProcessPool(
        env_resolver=_ai_env_resolver,
        model_resolver=_ai_model_resolver,
    )
    app.state.process_pool = pool

    # IMPL-0011 Phase F3: register the singleton-restart hook on app.state
    # so AIIntegrationService instances built per-request can push the
    # new env into the singleton OpenCode without coupling to main.
    async def _ai_on_key_change(env: dict[str, str]) -> None:
        # ``verify=False`` skips a second upstream auth probe — the
        # caller (BYOK / adopt / set_model route) already validated and
        # we'd just duplicate that call inside the mutation latency.
        await _refresh_ai_env_cache(verify=False)
        try:
            opencode_process.set_extra_env(env)
            if opencode_process.is_running:
                await opencode_process.restart()
        except Exception:
            logger.warning(
                "Singleton OpenCode restart after AI key change failed",
                exc_info=True,
            )

    app.state.ai_on_key_change = _ai_on_key_change

    # Agent executor (Layer 5: orchestration)
    app.state.agent_executor = AgentExecutor(pool, context_builder)

    # Background idle cleanup task
    async def _idle_cleanup_loop() -> None:
        idle_timeout = timedelta(seconds=settings.workspace_idle_timeout_seconds)
        while True:
            await asyncio.sleep(60)
            try:
                await pool.stop_idle(idle_timeout)
            except Exception:
                logger.exception("Error in workspace idle cleanup")

    cleanup_task = asyncio.create_task(_idle_cleanup_loop())

    # Background ingest worker (ADR-0023)
    ingest_task: asyncio.Task[None] | None = None
    if db_connection._db is not None:
        ingest_task = asyncio.create_task(ingest_worker_loop(db_connection._db))

    # Assessment watchdog — reaps wedged ``pending``/``running`` rows the
    # outer asyncio.timeout in ``api/_background.py`` couldn't catch (e.g.
    # the row was inserted but ``asyncio.create_task`` never ran the
    # worker). Migration 015 — failure surfacing.
    assessment_watchdog_task: asyncio.Task[None] | None = None
    if db_connection._db is not None:
        from cliff.db.dao.assessment import reap_stale_assessments

        async def _assessment_watchdog_loop() -> None:
            interval_s = settings.assessment_watchdog_interval_seconds
            stale_after_s = settings.assessment_stale_threshold_seconds
            while True:
                await asyncio.sleep(interval_s)
                try:
                    reaped = await reap_stale_assessments(
                        db_connection._db, older_than_seconds=stale_after_s
                    )
                    if reaped:
                        logger.warning(
                            "assessment watchdog reaped %d stale row(s)", reaped
                        )
                except Exception:
                    logger.exception("assessment watchdog tick failed")

        assessment_watchdog_task = asyncio.create_task(_assessment_watchdog_loop())

    yield

    logger.info("Shutting down Cliff...")
    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task

    if ingest_task is not None:
        ingest_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ingest_task

    if assessment_watchdog_task is not None:
        assessment_watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await assessment_watchdog_task

    await pool.stop_all()
    gh_orchestrator = getattr(app.state, "github_app_orchestrator", None)
    if gh_orchestrator is not None:
        await gh_orchestrator.stop_all()
    if app.state.audit_logger is not None:
        await app.state.audit_logger.stop()
    await opencode_client.close()
    await opencode_process.stop()
    await close_db()


app = FastAPI(
    title="Cliff",
    description="Self-hosted cybersecurity remediation copilot",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for dev (Vite on 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health.router)
app.include_router(version.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(findings.router, prefix="/api")
app.include_router(workspaces.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(agent_runs.router, prefix="/api")
app.include_router(agent_execution.router, prefix="/api")
app.include_router(sidebar.router, prefix="/api")
app.include_router(seed.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(github_app.router, prefix="/api")
app.include_router(ai_integrations.router, prefix="/api")

# EXEC-0002 contract stubs — routers registered so the OpenAPI schema is
# stable. Bodies raise NotImplementedError; real logic ships in Sessions B/C.
app.include_router(onboarding.router, prefix="/api")
app.include_router(assessment.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(posture.router, prefix="/api")
app.include_router(completion.router, prefix="/api")
app.include_router(config_routes.router, prefix="/api")

# Serve built frontend in production (when CLIFF_STATIC_DIR is set)
_static_dir = Path(settings.static_dir) if settings.static_dir else None
if _static_dir and _static_dir.is_dir():
    # Serve static assets (JS, CSS, images) under /assets
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    # SPA fallback: serve index.html for all non-API, non-health routes
    _index_html = _static_dir / "index.html"

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str) -> FileResponse:
        """Serve the SPA index.html for client-side routing."""
        # Try to serve a static file first (favicon, etc.)
        candidate = _static_dir / full_path
        if full_path and candidate.is_file() and _static_dir in candidate.resolve().parents:
            return FileResponse(str(candidate))
        return FileResponse(str(_index_html))
