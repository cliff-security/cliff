"""Tests for the eager profile-build wiring (ADR-0053 Phase 1.7)."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic_ai.models.test import TestModel

from cliff.repos import git_ops
from cliff.repos.profile_agents import make_profile_builders
from cliff.repos.profile_runner import ProfileRunner
from cliff.repos.repo_dir_manager import RepoDirManager
from cliff.repos.service import build_profile_runner, schedule_profile_build


def test_build_profile_runner_wires_production_adapters(db, tmp_path):
    """The production runner uses the real git adapters + all three builders."""
    mgr = RepoDirManager(tmp_path / "repos")

    async def token():
        return None

    runner = build_profile_runner(
        db, model=TestModel(), token_provider=token, dir_mgr=mgr
    )
    assert runner._sync_clone is git_ops.sync_clone
    assert runner._head_sha is git_ops.git_head_sha
    assert set(runner._builders) == {"profile", "code_map", "threat"}


async def test_end_to_end_with_real_git_adapters(db, bare_repo, tmp_path):
    """Real git_ops.sync_clone + real git_head_sha + TestModel builders profile a
    canonical (github-shaped) repo end to end, offline — the clone source is the
    local bare repo, everything else is production code."""
    mgr = RepoDirManager(tmp_path / "repos")

    async def redirect_sync(canonical_url, clone_dir, token):
        # Exercise the REAL adapter, just pointed at the offline bare repo.
        await git_ops.sync_clone(f"file://{bare_repo}", clone_dir, None, timeout_s=30)

    async def token():
        return None

    runner = ProfileRunner(
        db,
        mgr,
        builders=make_profile_builders(TestModel(custom_output_args={"kind": "service"})),
        sync_clone=redirect_sync,
        head_sha=git_ops.git_head_sha,
        token_provider=token,
    )
    repo = await runner.build("https://github.com/acme/web")

    assert repo.canonical_url == "https://github.com/acme/web"
    assert repo.profile_status == "ready"
    assert len(repo.last_profiled_sha) == 40  # a real sha read from the real clone
    assert mgr.read_artifact(repo.id, "profile")["kind"] == "service"
    assert (mgr.clone_dir(repo.id) / "README.md").exists()


async def test_schedule_profile_build_skips_without_ai(db):
    """No configured AI provider → best-effort no-op (never blocks the scan)."""
    app = SimpleNamespace(state=SimpleNamespace(ai_env_cache={}, ai_model_cache=None))
    assert schedule_profile_build(app, db, "https://github.com/a/b") is None


async def test_schedule_profile_build_skips_on_bad_model(db):
    """A configured-but-unbuildable model is skipped, not raised."""
    app = SimpleNamespace(
        state=SimpleNamespace(
            ai_env_cache={"ANTHROPIC_API_KEY": "x"},
            ai_model_cache="not-a-valid-id-without-slash",
        )
    )
    assert schedule_profile_build(app, db, "https://github.com/a/b") is None
