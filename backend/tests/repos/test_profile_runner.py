"""End-to-end test of the per-repo profile build flow with injected fakes.

Proves the Phase-1 backbone (mutex + clone + store + manifest + status
lifecycle) without any real LLM or network — the real builders just satisfy the
injected ``ProfileBuilder`` shape.
"""

from __future__ import annotations

import pytest

from cliff.repos.dao import get_repo, try_begin_profile
from cliff.repos.profile_runner import ProfileRunner
from cliff.repos.repo_dir_manager import RepoDirManager

URL = "https://github.com/acme/web"


class _Fakes:
    def __init__(self):
        self.builder_calls: list[str] = []
        self.clone_calls: list[tuple[str, str | None]] = []

    def builder(self, name, payload):
        async def _b(clone_dir):
            self.builder_calls.append(name)
            return payload

        return _b

    async def sync_clone(self, canonical_url, clone_dir, token):
        self.clone_calls.append((canonical_url, token))
        clone_dir.mkdir(parents=True, exist_ok=True)

    async def head_sha(self, clone_dir):
        return "abcd1234"

    async def token(self):
        return "ghp_tok"


@pytest.fixture
def runner(db, tmp_path):
    fakes = _Fakes()
    mgr = RepoDirManager(tmp_path / "repos")
    r = ProfileRunner(
        db,
        mgr,
        builders={
            "profile": fakes.builder("profile", {"kind": "service"}),
            "code_map": fakes.builder("code_map", {"ships_roots": ["src/**"]}),
            "threat": fakes.builder("threat", {"prior_issues": []}),
        },
        sync_clone=fakes.sync_clone,
        head_sha=fakes.head_sha,
        token_provider=fakes.token,
    )
    return r, fakes, mgr


async def test_build_happy_path(runner, db):
    r, fakes, mgr = runner
    repo = await r.build(URL)

    assert repo.profile_status == "ready"
    assert repo.last_profiled_sha == "abcd1234"
    assert repo.profile_dir == mgr.repo_dir(repo.id)
    assert repo.profiled_at is not None
    # All three artifacts written + manifest + digest.
    assert mgr.read_artifact(repo.id, "profile") == {"kind": "service"}
    assert mgr.read_artifact(repo.id, "code_map") == {"ships_roots": ["src/**"]}
    assert set(mgr.read_manifest(repo.id)["artifacts"]) == {"profile", "code_map", "threat"}
    assert mgr.read_manifest(repo.id)["source_sha"] == "abcd1234"
    assert mgr.profile_md_path(repo.id).exists()
    assert sorted(fakes.builder_calls) == ["code_map", "profile", "threat"]


async def test_token_is_passed_to_clone(runner):
    r, fakes, _mgr = runner
    await r.build(URL)
    assert fakes.clone_calls == [(URL, "ghp_tok")]


async def test_build_skips_when_mutex_already_held(runner, db):
    r, fakes, _mgr = runner
    # Simulate a build already in flight by grabbing the mutex first.
    from cliff.repos.dao import get_or_create_repo

    repo = await get_or_create_repo(db, URL)
    assert await try_begin_profile(db, repo.id) is True

    result = await r.build(URL)
    # The runner must not run builders while another build holds the mutex.
    assert result.profile_status == "building"
    assert fakes.builder_calls == []


async def test_builder_error_marks_error_and_reraises(db, tmp_path):
    mgr = RepoDirManager(tmp_path / "repos")

    async def boom(clone_dir):
        raise RuntimeError("profiler crashed")

    async def sync_clone(url, clone_dir, token):
        clone_dir.mkdir(parents=True, exist_ok=True)

    async def head_sha(clone_dir):
        return "sha"

    async def token():
        return None

    r = ProfileRunner(
        db,
        mgr,
        builders={"profile": boom},
        sync_clone=sync_clone,
        head_sha=head_sha,
        token_provider=token,
    )
    with pytest.raises(RuntimeError, match="profiler crashed"):
        await r.build(URL)

    repo = await get_repo(db, (await get_repo_id(db)))
    assert repo.profile_status == "error"


async def get_repo_id(db):
    from cliff.repos.dao import list_repos

    return (await list_repos(db))[0].id
