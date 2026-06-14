"""Fixtures for repo-knowledge-base tests — in-memory SQLite with migrations."""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture
async def db():
    """An aiosqlite.Connection backed by an in-memory DB with all migrations run."""
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()


@pytest.fixture
def git_run():
    """Run a git command offline (no global config / credential prompts)."""

    def _run(*args, cwd=None):
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/tmp", "PATH": "/usr/bin:/bin"},
        )

    return _run


@pytest.fixture
def bare_repo(tmp_path, git_run):
    """A local bare repo (one commit) usable as an offline clone source."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git_run("init", "-q", "-b", "main", cwd=seed)
    git_run("config", "user.email", "t@t.t", cwd=seed)
    git_run("config", "user.name", "t", cwd=seed)
    (seed / "README.md").write_text("# svc\nv1\n")
    git_run("add", "README.md", cwd=seed)
    git_run("commit", "-q", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    git_run("clone", "-q", "--bare", str(seed), str(bare))
    return bare
