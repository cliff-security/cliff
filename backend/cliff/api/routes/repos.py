"""Repo Project-profile API (ADR-0053 / PRD-0009 Phase 1.8).

Surfaces the per-repo profile freshness for the dashboard ("Cliff understands
your project; built N ago") and a re-profile action. Read path is the ``repo``
row + the generated ``PROFILE.md``; the rebuild path schedules the same eager
build the scan uses.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 — Pydantic needs this at runtime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FastAPIRequest
from pydantic import BaseModel

from cliff.db.connection import get_db
from cliff.repos.dao import get_repo_by_url
from cliff.repos.service import schedule_profile_build

router = APIRouter(prefix="/repos", tags=["repos"])


class RepoProfileStatus(BaseModel):
    repo_url: str | None = None
    #: none | building | ready | stale | error
    status: str = "none"
    profiled_at: datetime | None = None
    last_profiled_sha: str | None = None
    #: The generated PROFILE.md digest, when a profile exists.
    profile_md: str | None = None


class RebuildBody(BaseModel):
    repo_url: str | None = None


class RebuildResponse(BaseModel):
    #: scheduled | skipped
    status: str
    repo_url: str | None = None
    #: present when skipped (e.g. ``no_ai_provider``)
    reason: str | None = None


async def _resolve_repo_url(db, explicit: str | None) -> str | None:
    """The explicit url, else the connected GitHub integration's repo."""
    if explicit and explicit.strip():
        return explicit.strip()
    from cliff.db.repo_integration import list_integrations

    integrations = await list_integrations(db)
    github = next(
        (i for i in integrations if i.provider_name.lower() == "github" and i.enabled),
        None,
    )
    if github and github.config:
        url = github.config.get("repo_url")
        if url:
            return url
    return None


@router.get("/profile", response_model=RepoProfileStatus)
async def get_profile(
    repo_url: str | None = None, db=Depends(get_db)
) -> RepoProfileStatus:
    """The Project-profile status + freshness for the (current or given) repo."""
    url = await _resolve_repo_url(db, repo_url)
    if url is None:
        return RepoProfileStatus()

    repo = await get_repo_by_url(db, url)
    if repo is None:
        return RepoProfileStatus(repo_url=url, status="none")

    profile_md: str | None = None
    if repo.profile_dir:
        md_path = Path(repo.profile_dir) / "PROFILE.md"
        if md_path.exists():
            try:
                profile_md = md_path.read_text()
            except OSError:
                profile_md = None

    return RepoProfileStatus(
        repo_url=repo.canonical_url,
        status=repo.profile_status,
        profiled_at=repo.profiled_at,
        last_profiled_sha=repo.last_profiled_sha,
        profile_md=profile_md,
    )


@router.post("/profile/rebuild", response_model=RebuildResponse)
async def rebuild_profile(
    body: RebuildBody, http_request: FastAPIRequest, db=Depends(get_db)
) -> RebuildResponse:
    """Schedule a re-profile of the (current or given) repo."""
    url = await _resolve_repo_url(db, body.repo_url)
    if url is None:
        raise HTTPException(
            status_code=422, detail="No repository to profile — connect one first."
        )
    task = schedule_profile_build(http_request.app, db, url)
    if task is None:
        return RebuildResponse(status="skipped", repo_url=url, reason="no_ai_provider")
    return RebuildResponse(status="scheduled", repo_url=url)
