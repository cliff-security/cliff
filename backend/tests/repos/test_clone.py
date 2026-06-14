"""Tests for the credential-less clone + GC (ADR-0053 §4).

Network is avoided: the clone/refresh tests run against a local bare git repo.
The security property (no token in argv / in .git/config) is covered by unit
tests on the pure pieces plus the clean-config assertion after a real local clone.
"""

from __future__ import annotations

import subprocess

import pytest

from cliff.repos.clone import (
    TOKEN_ENV,
    _clone_args,
    _git_env,
    askpass_response,
    clone_repo,
    refresh_repo,
)
from cliff.repos.gc import gc_repo_clones

TOKEN = "ghp_supersecrettoken"


# ── the token never reaches argv (only the env) ─────────────────────────────


def test_clone_args_never_contain_the_token():
    args = _clone_args("https://github.com/acme/web", "/tmp/x", depth=1)
    assert TOKEN not in " ".join(args)
    assert "https://github.com/acme/web" in args  # plain url, no creds


def test_token_lives_only_in_env():
    env = _git_env(TOKEN, askpass_path="/tmp/askpass.sh")
    assert env[TOKEN_ENV] == TOKEN
    assert env["GIT_ASKPASS"] == "/tmp/askpass.sh"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_no_askpass_env_without_token():
    env = _git_env(None, askpass_path=None)
    assert TOKEN_ENV not in env
    assert "GIT_ASKPASS" not in env


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Username for 'https://github.com': ", "x-access-token"),
        ("Password for 'https://x-access-token@github.com': ", TOKEN),
    ],
)
def test_askpass_response(prompt, expected):
    assert askpass_response(prompt, TOKEN) == expected


# ── real clone/refresh against a local bare repo (offline) ──────────────────


def _git(*args, cwd=None):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/tmp", "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def bare_remote(tmp_path):
    """A local bare repo (one commit) + a working clone that tracks it.

    Returns ``(work, bare)``: ``bare`` is the clone source for the tests;
    ``work`` has ``origin=bare`` so a test can commit + push a new commit.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-q", "-b", "main", cwd=seed)
    _git("config", "user.email", "t@t.t", cwd=seed)
    _git("config", "user.name", "t", cwd=seed)
    (seed / "hello.txt").write_text("v1\n")
    _git("add", "hello.txt", cwd=seed)
    _git("commit", "-q", "-m", "v1", cwd=seed)
    bare = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(seed), str(bare))

    work = tmp_path / "work"
    _git("clone", "-q", f"file://{bare}", str(work))
    _git("config", "user.email", "t@t.t", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    return work, bare


async def test_clone_repo_offline_no_token_clean_config(bare_remote, tmp_path):
    _work, bare = bare_remote
    target = tmp_path / "clone"
    await clone_repo(f"file://{bare}", target=target, token=None, timeout_s=30)
    assert (target / "hello.txt").read_text() == "v1\n"
    # The security invariant: no token, not even x-access-token, in the config.
    config = (target / ".git" / "config").read_text()
    assert "x-access-token" not in config
    assert TOKEN not in config


async def test_refresh_repo_pulls_new_commit(bare_remote, tmp_path):
    work, bare = bare_remote
    target = tmp_path / "clone"
    await clone_repo(f"file://{bare}", target=target, token=None, timeout_s=30)

    # New commit lands on the remote.
    (work / "hello.txt").write_text("v2\n")
    _git("commit", "-q", "-am", "v2", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)

    await refresh_repo(target, token=None, timeout_s=30)
    assert (target / "hello.txt").read_text() == "v2\n"


# ── GC ──────────────────────────────────────────────────────────────────────


def _make_clone(base, repo_id, nbytes):
    clone = base / repo_id / "repo"
    clone.mkdir(parents=True)
    (clone / "blob.bin").write_bytes(b"x" * nbytes)
    # keep a profile artifact alongside to prove GC never removes it
    (base / repo_id / "profile.json").write_text("{}")
    return clone


def test_gc_under_budget_is_noop(tmp_path):
    base = tmp_path / "repos"
    _make_clone(base, "a", 100)
    assert gc_repo_clones(base, max_total_bytes=10_000) == []
    assert (base / "a" / "repo").exists()


def test_gc_evicts_lru_clone_keeps_artifacts(tmp_path):
    import os
    import time

    base = tmp_path / "repos"
    old = _make_clone(base, "old", 5_000)
    _make_clone(base, "new", 5_000)
    # Make "old" least-recently-used.
    past = time.time() - 1000
    os.utime(old, (past, past))

    evicted = gc_repo_clones(base, max_total_bytes=6_000)
    assert evicted == ["old"]
    assert not (base / "old" / "repo").exists()
    assert (base / "new" / "repo").exists()
    # GC never removes the profile artifacts — only the re-clonable clone.
    assert (base / "old" / "profile.json").exists()


def test_gc_empty_base(tmp_path):
    assert gc_repo_clones(tmp_path / "nope", max_total_bytes=10) == []
