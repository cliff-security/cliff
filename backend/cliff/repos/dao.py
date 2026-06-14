"""Data access for the ``repo`` entity (ADR-0053).

Kept in the feature package (not ``cliff.db.repo_*``) to avoid the naming
collision between the git-repository entity and the data-access
("repository pattern") modules. Functions take an ``aiosqlite.Connection``
like the rest of the DAO layer.

All timestamps are written as Python UTC isoformat strings so ordering
comparisons (the stale-build reaper) are consistent — the table's
``datetime('now')`` defaults are a fallback we don't rely on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from cliff.models.repo import Repo, RepoProfileStatus
from cliff.repos.identity import canonicalize_repo_url

if TYPE_CHECKING:
    import aiosqlite


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_repo(row: aiosqlite.Row) -> Repo:
    return Repo(
        id=row["id"],
        canonical_url=row["canonical_url"],
        default_branch=row["default_branch"],
        last_profiled_sha=row["last_profiled_sha"],
        profiled_at=row["profiled_at"],
        profile_status=row["profile_status"],
        profile_dir=row["profile_dir"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_or_create_repo(db: aiosqlite.Connection, repo_url: str) -> Repo:
    """Return the repo for *repo_url*, creating it on first sight.

    The URL is canonicalized first, so every spelling of the same repository
    resolves to one row.
    """
    canonical = canonicalize_repo_url(repo_url)
    now = _now()
    await db.execute(
        """
        INSERT INTO repo (id, canonical_url, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(canonical_url) DO NOTHING
        """,
        (uuid.uuid4().hex, canonical, now, now),
    )
    await db.commit()
    repo = await _get_by_canonical(db, canonical)
    assert repo is not None  # just inserted or already present
    return repo


async def _get_by_canonical(
    db: aiosqlite.Connection, canonical: str
) -> Repo | None:
    cursor = await db.execute(
        "SELECT * FROM repo WHERE canonical_url = ?", (canonical,)
    )
    row = await cursor.fetchone()
    return _row_to_repo(row) if row else None


async def get_repo(db: aiosqlite.Connection, repo_id: str) -> Repo | None:
    cursor = await db.execute("SELECT * FROM repo WHERE id = ?", (repo_id,))
    row = await cursor.fetchone()
    return _row_to_repo(row) if row else None


async def get_repo_by_url(db: aiosqlite.Connection, repo_url: str) -> Repo | None:
    """Look up a repo by any spelling of its URL (canonicalized first)."""
    return await _get_by_canonical(db, canonicalize_repo_url(repo_url))


async def list_repos(db: aiosqlite.Connection) -> list[Repo]:
    cursor = await db.execute("SELECT * FROM repo ORDER BY canonical_url")
    return [_row_to_repo(row) for row in await cursor.fetchall()]


async def try_begin_profile(db: aiosqlite.Connection, repo_id: str) -> bool:
    """Acquire the one-build-per-repo mutex (ADR-0053 §6).

    Compare-and-swap on ``profile_status``: flips the single repo row to
    ``building`` only if it is not already building. Returns ``True`` when this
    caller acquired the build, ``False`` when a build is already in progress
    (or the repo doesn't exist).
    """
    cursor = await db.execute(
        """
        UPDATE repo
        SET profile_status = 'building', updated_at = ?
        WHERE id = ? AND profile_status != 'building'
        """,
        (_now(), repo_id),
    )
    await db.commit()
    return cursor.rowcount == 1


async def finish_profile(
    db: aiosqlite.Connection,
    repo_id: str,
    *,
    status: RepoProfileStatus,
    sha: str | None = None,
    profile_dir: str | None = None,
) -> Repo | None:
    """Release the build mutex with a terminal *status*.

    On ``ready`` the freshness fields (``last_profiled_sha``, ``profiled_at``,
    ``profile_dir``) are stamped; on ``error`` only the status changes so the
    previous good profile's freshness survives.
    """
    now = _now()
    if status == "ready":
        await db.execute(
            """
            UPDATE repo
            SET profile_status = 'ready',
                last_profiled_sha = COALESCE(?, last_profiled_sha),
                profiled_at = ?,
                profile_dir = COALESCE(?, profile_dir),
                updated_at = ?
            WHERE id = ?
            """,
            (sha, now, profile_dir, now, repo_id),
        )
    else:
        await db.execute(
            "UPDATE repo SET profile_status = ?, updated_at = ? WHERE id = ?",
            (status, now, repo_id),
        )
    await db.commit()
    return await get_repo(db, repo_id)


async def mark_stale(db: aiosqlite.Connection, repo_id: str) -> Repo | None:
    await db.execute(
        "UPDATE repo SET profile_status = 'stale', updated_at = ? WHERE id = ?",
        (_now(), repo_id),
    )
    await db.commit()
    return await get_repo(db, repo_id)


async def reap_stale_builds(
    db: aiosqlite.Connection, *, older_than_seconds: float
) -> int:
    """Mark profile builds that have been ``building`` past the threshold as
    ``error`` (watchdog — the build task died without releasing the mutex).

    Returns the number of rows reaped.
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_seconds)).isoformat()
    cursor = await db.execute(
        """
        UPDATE repo
        SET profile_status = 'error', updated_at = ?
        WHERE profile_status = 'building' AND updated_at < ?
        """,
        (_now(), cutoff),
    )
    await db.commit()
    return cursor.rowcount
