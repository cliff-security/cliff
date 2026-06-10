"""ProfileRunner — orchestrates one per-repo Project-profile build (ADR-0053).

Ties together the pieces built in Phase 1: get-or-create the repo, acquire the
one-build-per-repo mutex, sync the cached clone, run the profile builders, write
their artifacts + the manifest + the generated digest, and release the mutex
with a terminal status.

The builders, the clone sync, the HEAD-sha read, and the token lookup are all
*injected* — so the whole flow is testable end-to-end with fakes, and the real
LLM builders (repo_profiler/code_map/threat_history) just satisfy the
``ProfileBuilder`` shape. Eager-at-scan wiring (PRD-0009) calls ``build`` as a
background task.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.repos.dao import (
    finish_profile,
    get_or_create_repo,
    get_repo,
    try_begin_profile,
)

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

    from cliff.models.repo import Repo
    from cliff.repos.repo_dir_manager import RepoDirManager

logger = logging.getLogger(__name__)

#: A builder reads the cached clone and returns one artifact dict.
ProfileBuilder = Callable[["Path"], Awaitable[dict]]
#: Bring the cached clone to the current remote tip (clone or fetch+reset).
SyncClone = Callable[[str, "Path", "str | None"], Awaitable[None]]
#: Read the checked-out HEAD sha of a clone.
HeadSha = Callable[["Path"], Awaitable[str]]
#: Look up the GitHub token (from the vault), or None when unconfigured.
TokenProvider = Callable[[], Awaitable["str | None"]]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ProfileRunner:
    def __init__(
        self,
        db: aiosqlite.Connection,
        dir_mgr: RepoDirManager,
        *,
        builders: dict[str, ProfileBuilder],
        sync_clone: SyncClone,
        head_sha: HeadSha,
        token_provider: TokenProvider,
    ) -> None:
        self._db = db
        self._dir = dir_mgr
        self._builders = builders
        self._sync_clone = sync_clone
        self._head_sha = head_sha
        self._token_provider = token_provider

    async def build(self, repo_url: str) -> Repo | None:
        """Build (or rebuild) the Project profile for *repo_url*.

        Returns the repo row. If a build is already in progress the mutex is not
        acquired and the existing row is returned untouched (no double work).
        """
        repo = await get_or_create_repo(self._db, repo_url)
        if not await try_begin_profile(self._db, repo.id):
            logger.info("profile build already in progress for %s", repo.canonical_url)
            return await get_repo(self._db, repo.id)

        try:
            token = await self._token_provider()
            clone_dir = self._dir.clone_dir(repo.id)
            await self._sync_clone(repo.canonical_url, clone_dir, token)
            sha = await self._head_sha(clone_dir)

            for name, builder in self._builders.items():
                self._dir.write_artifact(repo.id, name, await builder(clone_dir))

            self._dir.write_manifest(repo.id, source_sha=sha, built_at=_now())
            self._dir.regenerate_profile_md(repo.id)

            return await finish_profile(
                self._db,
                repo.id,
                status="ready",
                sha=sha,
                profile_dir=self._dir.repo_dir(repo.id),
            )
        except Exception:
            logger.exception("profile build failed for %s", repo.canonical_url)
            await finish_profile(self._db, repo.id, status="error")
            raise
