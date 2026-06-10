"""Unit tests for the repo entity DAO + migration 025 (ADR-0053)."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from cliff.repos.dao import (
    finish_profile,
    get_or_create_repo,
    get_repo,
    get_repo_by_url,
    list_repos,
    reap_stale_builds,
    try_begin_profile,
)

A = "https://github.com/acme/web"


async def test_get_or_create_dedups_across_spellings(db):
    one = await get_or_create_repo(db, A)
    two = await get_or_create_repo(db, "git@github.com:acme/web.git")
    three = await get_or_create_repo(db, "https://github.com/acme/web/")
    assert one.id == two.id == three.id
    assert one.canonical_url == A
    assert len(await list_repos(db)) == 1


async def test_new_repo_defaults(db):
    repo = await get_or_create_repo(db, A)
    assert repo.profile_status == "none"
    assert repo.profiled_at is None
    assert repo.profile_dir is None
    assert repo.last_profiled_sha is None
    assert repo.created_at is not None


async def test_get_repo_by_url_finds_via_variant(db):
    created = await get_or_create_repo(db, A)
    found = await get_repo_by_url(db, "HTTPS://GitHub.com/acme/web.git")
    assert found is not None
    assert found.id == created.id


async def test_get_repo_missing(db):
    assert await get_repo(db, "nope") is None


async def test_canonical_url_is_unique(db):
    await get_or_create_repo(db, A)
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO repo (id, canonical_url, created_at, updated_at) VALUES (?,?,?,?)",
            ("dup", A, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        await db.commit()


# ── the one-build-per-repo mutex (CAS) ──────────────────────────────────────


async def test_try_begin_profile_is_a_mutex(db):
    repo = await get_or_create_repo(db, A)
    assert await try_begin_profile(db, repo.id) is True
    # A second attempt while building is rejected — the mutex is held.
    assert await try_begin_profile(db, repo.id) is False

    refreshed = await get_repo(db, repo.id)
    assert refreshed.profile_status == "building"


async def test_finish_profile_ready_stamps_freshness_and_releases(db):
    repo = await get_or_create_repo(db, A)
    await try_begin_profile(db, repo.id)
    done = await finish_profile(
        db, repo.id, status="ready", sha="abc123", profile_dir="data/repos/x"
    )
    assert done.profile_status == "ready"
    assert done.last_profiled_sha == "abc123"
    assert done.profile_dir == "data/repos/x"
    assert done.profiled_at is not None
    # Mutex released — a rebuild can be acquired again.
    assert await try_begin_profile(db, repo.id) is True


async def test_finish_profile_error_preserves_prior_freshness(db):
    repo = await get_or_create_repo(db, A)
    await try_begin_profile(db, repo.id)
    await finish_profile(db, repo.id, status="ready", sha="good-sha", profile_dir="d")
    # A later build fails.
    await try_begin_profile(db, repo.id)
    errored = await finish_profile(db, repo.id, status="error")
    assert errored.profile_status == "error"
    # The previous good profile's freshness survives an error.
    assert errored.last_profiled_sha == "good-sha"
    assert errored.profile_dir == "d"


async def test_try_begin_profile_missing_repo(db):
    assert await try_begin_profile(db, "ghost") is False


# ── stale-build reaper (watchdog) ───────────────────────────────────────────


async def test_reap_stale_builds_marks_old_building_rows_error(db):
    repo = await get_or_create_repo(db, A)
    await try_begin_profile(db, repo.id)
    await asyncio.sleep(0.05)
    reaped = await reap_stale_builds(db, older_than_seconds=0.001)
    assert reaped == 1
    assert (await get_repo(db, repo.id)).profile_status == "error"


async def test_reap_stale_builds_skips_recent(db):
    repo = await get_or_create_repo(db, A)
    await try_begin_profile(db, repo.id)
    reaped = await reap_stale_builds(db, older_than_seconds=60.0)
    assert reaped == 0
    assert (await get_repo(db, repo.id)).profile_status == "building"


async def test_reap_stale_builds_ignores_non_building(db):
    await get_or_create_repo(db, A)  # status 'none' — never building
    reaped = await reap_stale_builds(db, older_than_seconds=0.0)
    assert reaped == 0
