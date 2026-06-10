"""Offline tests for the pinned-SHA checkout (ADR-0052 live-lane eval).

Uses a local two-commit bare repo (allowAnySHA1InWant enabled) to prove the
vulnerable/patched SHA-pair mechanism without network.
"""

from __future__ import annotations

import subprocess

import pytest

from cliff.evals.repo_fetch import CheckoutError, checkout_at_sha


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/tmp", "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def two_commit_bare(tmp_path):
    """A bare repo with two commits — the 'vulnerable' (c1) and 'patched' (c2)
    states of the same file — fetchable by SHA."""
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@t.t", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "f.txt").write_text("vulnerable\n")
    _git("add", "f.txt", cwd=work)
    _git("commit", "-q", "-m", "c1", cwd=work)
    sha_vuln = _git("rev-parse", "HEAD", cwd=work).stdout.strip()
    (work / "f.txt").write_text("patched\n")
    _git("commit", "-q", "-am", "c2", cwd=work)
    sha_fix = _git("rev-parse", "HEAD", cwd=work).stdout.strip()

    bare = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(work), str(bare))
    _git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=bare)
    _git("config", "uploadpack.allowReachableSHA1InWant", "true", cwd=bare)
    return bare, sha_vuln, sha_fix


async def test_checkout_vulnerable_then_patched_sha(two_commit_bare, tmp_path):
    bare, sha_vuln, sha_fix = two_commit_bare

    vuln = tmp_path / "vuln"
    await checkout_at_sha(f"file://{bare}", sha_vuln, vuln, timeout=30)
    assert (vuln / "f.txt").read_text() == "vulnerable\n"

    patched = tmp_path / "patched"
    await checkout_at_sha(f"file://{bare}", sha_fix, patched, timeout=30)
    assert (patched / "f.txt").read_text() == "patched\n"


async def test_checkout_bad_sha_raises(two_commit_bare, tmp_path):
    bare, _, _ = two_commit_bare
    with pytest.raises(CheckoutError):
        await checkout_at_sha(f"file://{bare}", "0" * 40, tmp_path / "x", timeout=30)


async def test_run_deep_dive_eval_walks_the_real_checkout(two_commit_bare, tmp_path):
    """The harness checks out the pinned commit and hands the REAL code to the
    pipeline — proving repo+sha cases work end to end (with a stub verdict)."""
    from cliff.agents.schemas import TriageOutput
    from cliff.evals.cases import EvalCase
    from cliff.evals.runners import run_deep_dive_eval

    bare, sha_vuln, _ = two_commit_bare
    case = EvalCase.model_validate(
        {
            "id": "vuln",
            "tier": "live",
            "finding": {"t": "x"},
            "repo": f"file://{bare}",
            "sha": sha_vuln,
            "expected": {"verdict": "real"},
        }
    )

    seen = {}

    async def stub(c, repo_dir):
        seen["content"] = (repo_dir / "f.txt").read_text()
        return TriageOutput(verdict="real", confidence=0.85)

    result = await run_deep_dive_eval([case], run_pipeline=stub)
    assert seen["content"] == "vulnerable\n"  # the agent saw the real checked-out code
    assert result.passed is True
