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

from opensec.agents.executor import AgentExecutor
from opensec.agents.template_engine import AgentTemplateEngine
from opensec.ai import catalog as ai_catalog
from opensec.api.routes import (
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
from opensec.api.routes import (
    config as config_routes,
)
from opensec.api.routes import (
    settings as settings_routes,
)
from opensec.config import settings
from opensec.db import connection as db_connection
from opensec.db.connection import close_db, init_db
from opensec.engine.client import opencode_client
from opensec.engine.config_manager import config_manager
from opensec.engine.pool import WorkspaceProcessPool
from opensec.engine.process import opencode_process
from opensec.integrations.audit import AuditLogger
from opensec.integrations.gateway import MCPConfigResolver
from opensec.integrations.ingest_worker import ingest_worker_loop
from opensec.integrations.vault import CredentialVault
from opensec.workspace.context_builder import WorkspaceContextBuilder
from opensec.workspace.workspace_dir_manager import WorkspaceDirManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start OpenCode on startup, stop on shutdown."""
    logger.info("Starting OpenSec...")
    # Surface any active AI model override at boot so operators see them
    # in stdout/stderr (ADR-0036 — performance may vary if a non-default
    # model is in use).
    ai_catalog.log_override_warnings_once()
    # Initialize persistence layer.
    db_path = settings.resolve_data_dir() / "opensec.db"
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
        from opensec.db.dao.assessment import reconcile_orphaned_assessments

        reconciled = await reconcile_orphaned_assessments(db_connection._db)
        if reconciled:
            logger.info(
                "Reconciled %d orphaned assessment row(s) to 'failed' on startup",
                reconciled,
            )

    # Demo mode: seed sample findings on startup
    if settings.demo and db_connection._db is not None:
        from opensec.api.routes.seed import DEMO_FINDINGS
        from opensec.db.repo_finding import create_finding, list_findings
        from opensec.models import FindingCreate

        existing = await list_findings(db_connection._db, limit=1)
        if not existing:
            logger.info("Demo mode: seeding %d sample findings", len(DEMO_FINDINGS))
            for data in DEMO_FINDINGS:
                await create_finding(db_connection._db, FindingCreate(**data))
            logger.info("Demo mode: seeding complete")
        else:
            logger.info("Demo mode: findings already exist, skipping seed")

    # Start AI engine (non-fatal if unavailable).
    try:
        await opencode_process.start()
        # Restore stored API keys and reconcile model config.
        try:
            if db_connection._db is not None:
                await config_manager.reconcile_model(db_connection._db)
                await config_manager.restore_keys_to_engine(db_connection._db)
        except Exception:
            logger.warning("Could not restore settings to OpenCode engine")
    except Exception:
        logger.exception("Failed to start OpenCode — app will run but engine is unavailable")

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
        try:
            app.state.vault = CredentialVault(db_connection._db)
            logger.info("Credential vault initialized")
        except Exception:
            logger.warning("Credential vault not available — set OPENSEC_CREDENTIAL_KEY to enable")

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

    # Layer 3: Per-workspace process pool.
    # IMPL-0011 Phase F2: wire an env resolver so every workspace spawn
    # automatically picks up the active AI provider key (env var per
    # provider). Resolver is async + closure-bound to app.state so it
    # always reads the current vault / db state, even after disconnect.
    async def _ai_env_resolver() -> dict[str, str]:
        from opensec.ai.service import AIIntegrationService

        vault = app.state.vault
        db = db_connection._db
        if vault is None or db is None:
            return {}
        service = AIIntegrationService(
            db, vault, audit_logger=app.state.audit_logger
        )
        try:
            return await service.resolve_env_for_workspace()
        except Exception:
            logger.warning(
                "AI integration env resolution failed", exc_info=True
            )
            return {}

    pool = WorkspaceProcessPool(env_resolver=_ai_env_resolver)
    app.state.process_pool = pool

    # IMPL-0011 Phase F3: register the singleton-restart hook on app.state
    # so AIIntegrationService instances built per-request can push the
    # new env into the singleton OpenCode without coupling to main.
    async def _ai_on_key_change(env: dict[str, str]) -> None:
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
        from opensec.db.dao.assessment import reap_stale_assessments

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

    logger.info("Shutting down OpenSec...")
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
    title="OpenSec",
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

# Serve built frontend in production (when OPENSEC_STATIC_DIR is set)
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
