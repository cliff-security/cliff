"""Offline tests for the real git adapters (ADR-0053 Phase 1.7)."""

from __future__ import annotations

import pytest

from cliff.repos.git_ops import git_head_sha, sync_clone


async def test_sync_clone_fresh_then_head_sha(bare_repo, tmp_path):
    clone = tmp_path / "store" / "rid" / "repo"
    await sync_clone(f"file://{bare_repo}", clone, None, timeout_s=30)
    assert (clone / "README.md").read_text().startswith("# svc")
    sha = await git_head_sha(clone)
    assert len(sha) == 40


async def test_sync_clone_refreshes_existing(bare_repo, tmp_path, git_run):
    clone = tmp_path / "store" / "rid" / "repo"
    await sync_clone(f"file://{bare_repo}", clone, None, timeout_s=30)
    first = await git_head_sha(clone)

    # Push a new commit to the remote via a throwaway work clone.
    work = tmp_path / "work"
    git_run("clone", "-q", f"file://{bare_repo}", str(work))
    git_run("config", "user.email", "t@t.t", cwd=work)
    git_run("config", "user.name", "t", cwd=work)
    (work / "README.md").write_text("# svc\nv2\n")
    git_run("commit", "-q", "-am", "v2", cwd=work)
    git_run("push", "-q", "origin", "main", cwd=work)

    # Second sync takes the refresh path (.git exists) and updates the tree.
    await sync_clone(f"file://{bare_repo}", clone, None, timeout_s=30)
    assert (clone / "README.md").read_text() == "# svc\nv2\n"
    assert await git_head_sha(clone) != first


async def test_sync_clone_replaces_stale_non_git_dir(bare_repo, tmp_path):
    clone = tmp_path / "store" / "rid" / "repo"
    clone.mkdir(parents=True)
    (clone / "leftover.txt").write_text("junk from a half-finished build")
    # No .git → the dir is removed and re-cloned cleanly.
    await sync_clone(f"file://{bare_repo}", clone, None, timeout_s=30)
    assert (clone / "README.md").exists()
    assert not (clone / "leftover.txt").exists()


async def test_git_head_sha_raises_on_non_repo(tmp_path):
    with pytest.raises(RuntimeError, match="rev-parse failed"):
        await git_head_sha(tmp_path)
