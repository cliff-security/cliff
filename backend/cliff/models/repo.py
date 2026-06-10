"""Repo entity (ADR-0053).

The first-class git-repository in Cliff. Its ``canonical_url`` (via
:func:`cliff.repos.identity.canonicalize_repo_url`) is the de-duplicating key,
and it is the queryable home for the Project-profile freshness the dashboard
shows. The profile artifacts themselves live on the filesystem under
``profile_dir``; this row is the metadata + freshness pointer (the hybrid
SQLite-metadata + filesystem-blob split, mirroring ``workspace`` +
``workspace_dir``).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 — Pydantic needs this at runtime
from typing import Literal

from pydantic import BaseModel

#: ``none`` — never profiled. ``building`` — a profile build holds the mutex.
#: ``ready`` — a fresh profile exists. ``stale`` — code moved past
#: ``last_profiled_sha``. ``error`` — the last build failed.
RepoProfileStatus = Literal["none", "building", "ready", "stale", "error"]


class Repo(BaseModel):
    id: str
    canonical_url: str
    default_branch: str | None = None
    last_profiled_sha: str | None = None
    profiled_at: datetime | None = None
    profile_status: RepoProfileStatus = "none"
    profile_dir: str | None = None
    created_at: datetime
    updated_at: datetime
