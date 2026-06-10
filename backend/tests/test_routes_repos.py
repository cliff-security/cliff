"""Route tests for the repo Project-profile API (ADR-0053 / PRD-0009 P1.8)."""

from __future__ import annotations

import cliff.db.connection as dbconn


async def test_get_profile_none_when_no_repo(db_client):
    resp = await db_client.get("/api/repos/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "none"
    assert body["repo_url"] is None


async def test_get_profile_ready(db_client, tmp_path):
    from cliff.repos.dao import finish_profile, get_or_create_repo, try_begin_profile

    conn = dbconn._db
    repo = await get_or_create_repo(conn, "https://github.com/acme/web")
    pdir = tmp_path / "store"
    pdir.mkdir()
    (pdir / "PROFILE.md").write_text("# Project profile\n## profile\n- kind: service\n")
    await try_begin_profile(conn, repo.id)
    await finish_profile(conn, repo.id, status="ready", sha="a" * 40, profile_dir=str(pdir))

    # Looked up by a different spelling — canonicalization resolves it.
    resp = await db_client.get(
        "/api/repos/profile", params={"repo_url": "git@github.com:acme/web.git"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["repo_url"] == "https://github.com/acme/web"
    assert body["last_profiled_sha"] == "a" * 40
    assert "service" in body["profile_md"]


async def test_get_profile_none_when_repo_unprofiled(db_client):
    resp = await db_client.get(
        "/api/repos/profile", params={"repo_url": "https://github.com/x/y"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "none"


async def test_rebuild_skipped_without_ai_provider(db_client):
    resp = await db_client.post(
        "/api/repos/profile/rebuild", json={"repo_url": "https://github.com/a/b"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "no_ai_provider"


async def test_rebuild_422_without_a_repo(db_client):
    resp = await db_client.post("/api/repos/profile/rebuild", json={})
    assert resp.status_code == 422
