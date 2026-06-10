"""Eager profile-build wiring (ADR-0053 / PRD-0009 Phase 1.7).

Assembles a real :class:`ProfileRunner` from the canonical AI state + the vault
GitHub token, and schedules a build as a tracked background task at scan time —
mirroring ``schedule_assessment_run``. Best-effort: if no AI provider is
configured the build is skipped (never blocks or breaks the assessment).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from cliff.config import settings
from cliff.repos.git_ops import git_head_sha, sync_clone
from cliff.repos.profile_agents import make_profile_builders
from cliff.repos.profile_runner import ProfileRunner, TokenProvider
from cliff.repos.repo_dir_manager import RepoDirManager

if TYPE_CHECKING:
    import aiosqlite
    from fastapi import FastAPI
    from pydantic_ai.models import Model

logger = logging.getLogger(__name__)


def default_repo_dir_manager() -> RepoDirManager:
    return RepoDirManager(settings.resolve_data_dir() / "repos")


def build_profile_runner(
    db: aiosqlite.Connection,
    *,
    model: Model,
    token_provider: TokenProvider,
    dir_mgr: RepoDirManager | None = None,
) -> ProfileRunner:
    """Assemble a production ProfileRunner (real clone + sha; injected model/token)."""
    return ProfileRunner(
        db,
        dir_mgr or default_repo_dir_manager(),
        builders=make_profile_builders(model),
        sync_clone=sync_clone,
        head_sha=git_head_sha,
        token_provider=token_provider,
    )


def schedule_profile_build(
    app: FastAPI, db: aiosqlite.Connection, repo_url: str
) -> asyncio.Task[None] | None:
    """Fire-and-track an eager Project-profile build for *repo_url*.

    Returns the task, or ``None`` when skipped (no AI provider configured / the
    model can't be built). Always best-effort — never raises into the caller.
    """
    env = dict(getattr(app.state, "ai_env_cache", {}) or {})
    model_id = getattr(app.state, "ai_model_cache", None)
    if not model_id or not env:
        logger.info("profile build skipped for %s — no AI provider configured", repo_url)
        return None

    try:
        from cliff.agents.runtime.provider import build_model

        model = build_model(env, model_id)
    except Exception:
        logger.warning("profile build skipped for %s — model unavailable", repo_url, exc_info=True)
        return None

    from cliff.api._engine_dep import _github_token_from_integration

    runner = build_profile_runner(
        db, model=model, token_provider=_github_token_from_integration
    )

    tasks: set[asyncio.Task[None]] = getattr(app.state, "profile_tasks", None) or set()

    async def _run() -> None:
        try:
            await runner.build(repo_url)
        except Exception:
            logger.exception("eager profile build failed for %s", repo_url)

    task = asyncio.create_task(_run(), name=f"profile:{repo_url}")
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    app.state.profile_tasks = tasks
    return task
