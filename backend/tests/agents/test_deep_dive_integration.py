"""Escalation → Deep dive gating (ADR-0052 P2.10).

Drives ``maybe_deep_dive`` with an injected runner + a real seeded profile, so
the gating logic (escalate? AI? ready profile? clone present?) is covered without
a model.
"""

from __future__ import annotations

import pytest

from cliff.agents.schemas import TriageOutput
from cliff.agents.triage_deep.integration import maybe_deep_dive
from cliff.repos.dao import finish_profile, get_or_create_repo, try_begin_profile
from cliff.repos.repo_dir_manager import RepoDirManager

URL = "https://github.com/acme/web"
AI_ENV = {"ANTHROPIC_API_KEY": "x"}
MODEL = "anthropic/claude-haiku-4-5"

NEEDS_REVIEW = TriageOutput(verdict="needs_review", confidence=0.5)
CLEAR = TriageOutput(verdict="unexploitable", confidence=0.9)
DEEP_RESULT = TriageOutput(verdict="real", confidence=0.9)


@pytest.fixture
async def db():
    from cliff.db.connection import close_db, init_db

    conn = await init_db(":memory:")
    try:
        yield conn
    finally:
        await close_db()


class _Runner:
    def __init__(self):
        self.called = False

    async def run(self, **kwargs):
        self.called = True
        self.kwargs = kwargs
        return DEEP_RESULT


class _Boom:
    async def run(self, **kwargs):
        raise AssertionError("runner must not be called")


async def _seed_ready_profile(db, tmp_path):
    mgr = RepoDirManager(tmp_path / "repos")
    repo = await get_or_create_repo(db, URL)
    for name in ("profile", "code_map", "threat"):
        mgr.write_artifact(repo.id, name, {"k": name})
    mgr.clone_dir(repo.id).mkdir(parents=True)
    await try_begin_profile(db, repo.id)
    await finish_profile(
        db, repo.id, status="ready", sha="a" * 40, profile_dir=mgr.repo_dir(repo.id)
    )
    return mgr


async def test_no_escalation_skips(db, tmp_path):
    mgr = await _seed_ready_profile(db, tmp_path)
    out = await maybe_deep_dive(
        db,
        finding={"raw_severity": "low"},
        quick=CLEAR,
        repo_url=URL,
        enrichment=None,
        exposure=None,
        ai_env=AI_ENV,
        model_full_id=MODEL,
        dir_mgr=mgr,
        runner=_Boom(),
    )
    assert out is None


async def test_escalates_and_runs_deep_dive(db, tmp_path):
    mgr = await _seed_ready_profile(db, tmp_path)
    runner = _Runner()
    out = await maybe_deep_dive(
        db,
        finding={},
        quick=NEEDS_REVIEW,
        repo_url=URL,
        enrichment={"e": 1},
        exposure={"x": 1},
        ai_env=AI_ENV,
        model_full_id=MODEL,
        dir_mgr=mgr,
        runner=runner,
    )
    assert out is DEEP_RESULT
    assert runner.called
    # The runner received the repo knowledge + the SHA-pinned clone.
    assert runner.kwargs["traced_sha"] == "a" * 40
    assert set(runner.kwargs["repo_knowledge"]) == {"profile", "code_map", "threat"}


async def test_no_ai_skips(db, tmp_path):
    mgr = await _seed_ready_profile(db, tmp_path)
    out = await maybe_deep_dive(
        db,
        finding={},
        quick=NEEDS_REVIEW,
        repo_url=URL,
        enrichment=None,
        exposure=None,
        ai_env={},
        model_full_id=None,
        dir_mgr=mgr,
        runner=_Boom(),
    )
    assert out is None


async def test_no_ready_profile_skips(db, tmp_path):
    mgr = RepoDirManager(tmp_path / "repos")  # repo never profiled
    out = await maybe_deep_dive(
        db,
        finding={},
        quick=NEEDS_REVIEW,
        repo_url=URL,
        enrichment=None,
        exposure=None,
        ai_env=AI_ENV,
        model_full_id=MODEL,
        dir_mgr=mgr,
        runner=_Boom(),
    )
    assert out is None
