"""Route tests for D1 onboarding (IMPL-0002)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cliff.api._engine_dep import get_assessment_engine
from cliff.assessment.posture.github_client import UnableToVerify
from cliff.main import app
from cliff.models import CriteriaSnapshot
from tests.fakes.assessment_engine import FakeAssessmentEngine


@pytest.fixture
def fake_engine():
    engine = FakeAssessmentEngine(
        grade="B",
        criteria=CriteriaSnapshot(posture_checks_total=2, posture_checks_passing=1),
        posture_checks=[{"check_name": "branch_protection", "status": "pass"}],
    )
    app.dependency_overrides[get_assessment_engine] = lambda: engine
    try:
        yield engine
    finally:
        app.dependency_overrides.pop(get_assessment_engine, None)


async def _drain() -> None:
    tasks = list(getattr(app.state, "assessment_tasks", []))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_connect_repo_creates_assessment(db_client, fake_engine):
    resp = await db_client.post(
        "/api/onboarding/repo",
        json={"repo_url": "https://github.com/a/b", "github_token": "ghp_xxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment_id"]
    assert data["repo_url"] == "https://github.com/a/b"

    await _drain()
    assert fake_engine.call_count == 1

    # PAT lands in a GitHub Integrations row — single source of truth for the
    # assessment engine, posture-fix spawner, and "solve a finding" flow.
    from cliff.db.connection import _db
    from cliff.db.repo_integration import list_integrations
    from cliff.db.repo_setting import get_setting

    integrations = await list_integrations(_db)
    github = next((i for i in integrations if i.adapter_type == "github"), None)
    assert github is not None, "onboarding must create a GitHub integration row"
    assert github.enabled is True
    assert github.config is not None
    assert github.config.get("repo_url") == "https://github.com/a/b"

    # Legacy app_setting location must not be written to any more.
    legacy = await get_setting(_db, "onboarding.github_token")
    assert legacy is None


async def test_connect_repo_empty_url_returns_422(db_client, fake_engine):
    resp = await db_client.post(
        "/api/onboarding/repo",
        json={"repo_url": "   ", "github_token": "ghp_xxx"},
    )
    assert resp.status_code == 422


async def test_connect_repo_without_token_returns_not_connected_when_vault_empty(
    db_client, fake_engine,
):
    """ADR-0035 collapsed endpoints: omitting ``github_token`` falls back
    to the vault. With no integration set up, that 422s with
    ``code=not_connected`` so the SPA can prompt the user to connect."""
    resp = await db_client.post(
        "/api/onboarding/repo",
        json={"repo_url": "https://github.com/a/b"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("code") == "not_connected"


async def test_list_github_repos_without_token_returns_not_connected_when_vault_empty(
    db_client,
):
    resp = await db_client.post(
        "/api/onboarding/github/repos",
        json={},
    )
    assert resp.status_code == 422
    assert resp.json().get("code") == "not_connected"


async def test_complete_onboarding_happy_path(db_client, fake_engine):
    run = await db_client.post(
        "/api/onboarding/repo",
        json={"repo_url": "https://github.com/a/b", "github_token": "ghp_xxx"},
    )
    aid = run.json()["assessment_id"]
    await _drain()

    resp = await db_client.post("/api/onboarding/complete", json={"assessment_id": aid})
    assert resp.status_code == 200
    assert resp.json() == {"onboarding_completed": True}

    from cliff.db.connection import _db
    from cliff.db.repo_setting import get_setting

    setting = await get_setting(_db, "onboarding.completed")
    assert setting.value == {"completed": True}


async def test_complete_onboarding_not_complete_returns_409(db_client):
    # Manually seed a pending assessment without running the fake engine.
    from cliff.db.connection import _db
    from cliff.db.dao.assessment import create_assessment
    from cliff.models import AssessmentCreate

    a = await create_assessment(_db, AssessmentCreate(repo_url="https://github.com/a/b"))

    resp = await db_client.post("/api/onboarding/complete", json={"assessment_id": a.id})
    assert resp.status_code == 409


async def test_complete_onboarding_unknown_assessment_returns_404(db_client):
    resp = await db_client.post("/api/onboarding/complete", json={"assessment_id": "nope"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Token scope enforcement on /onboarding/repo
# ---------------------------------------------------------------------------
#
# The autouse fixture in conftest.py stubs ``_probe_repo_metadata`` to
# always return None. These tests need the real probe with mocked GitHub
# responses, so they un-stub it (``_real_probe`` re-patches with the
# original function imported at module-load time) and patch
# ``GithubClient.get_repo_info`` underneath — then assert the route
# renders the right ``code``.

# Captured at import time, before the autouse fixture replaces it.
from cliff.api.routes.onboarding import (  # noqa: E402, N813
    _probe_repo_metadata as _original_probe,
)


def _real_probe():
    return patch(
        "cliff.api.routes.onboarding._probe_repo_metadata",
        new=_original_probe,
    )


def _patch_get_repo_info(return_value):
    return patch(
        "cliff.api.routes.onboarding.GithubClient.get_repo_info",
        new=AsyncMock(return_value=return_value),
    )


async def test_repo_with_push_succeeds(db_client, fake_engine):
    """200 with permissions.push=true → assessment scheduled, no error."""
    info = {
        "full_name": "org/repo",
        "private": True,
        "default_branch": "main",
        "permissions": {"push": True, "pull": True, "admin": False},
    }
    # Override the autouse stub so the real probe runs.
    with _real_probe(), _patch_get_repo_info(info):
        resp = await db_client.post(
            "/api/onboarding/repo",
            json={
                "repo_url": "https://github.com/org/repo",
                "github_token": "ghp_xxx",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"]["repo_name"] == "org/repo"
    assert "push" in body["verified"]["permissions"]
    await _drain()


async def test_repo_without_push_returns_missing_repo_scope(db_client, fake_engine):
    """200 with permissions.push=false → 422 missing_repo_scope, no scan."""
    info = {
        "full_name": "org/repo",
        "private": True,
        "default_branch": "main",
        "permissions": {"push": False, "pull": True},
    }
    with _real_probe(), _patch_get_repo_info(info):
        resp = await db_client.post(
            "/api/onboarding/repo",
            json={
                "repo_url": "https://github.com/org/repo",
                "github_token": "ghp_readonly",
            },
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "missing_repo_scope"
    # No assessment kicked off when probe hard-fails.
    assert fake_engine.call_count == 0


async def test_repo_403_returns_missing_repo_scope(db_client, fake_engine):
    with _real_probe(), _patch_get_repo_info(UnableToVerify(reason="http_403")):
        resp = await db_client.post(
            "/api/onboarding/repo",
            json={
                "repo_url": "https://github.com/org/repo",
                "github_token": "ghp_bad",
            },
        )
    assert resp.status_code == 422
    assert resp.json()["code"] == "missing_repo_scope"


async def test_repo_404_returns_repo_not_found(db_client, fake_engine):
    with _real_probe(), _patch_get_repo_info(UnableToVerify(reason="http_404")):
        resp = await db_client.post(
            "/api/onboarding/repo",
            json={
                "repo_url": "https://github.com/org/missing",
                "github_token": "ghp_ok",
            },
        )
    assert resp.status_code == 422
    assert resp.json()["code"] == "repo_not_found"


async def test_repo_network_error_keeps_legacy_soft_path(db_client, fake_engine):
    """Network/5xx → ``verified=None``, scan still scheduled (legacy behavior).

    Transient GitHub blips shouldn't strand a user mid-onboarding.
    """
    with _real_probe(), _patch_get_repo_info(
        UnableToVerify(reason="network: TimeoutException")
    ):
        resp = await db_client.post(
            "/api/onboarding/repo",
            json={
                "repo_url": "https://github.com/org/repo",
                "github_token": "ghp_ok",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is None
    assert body["assessment_id"]
    await _drain()
    assert fake_engine.call_count == 1


# ---------------------------------------------------------------------------
# /onboarding/github/repos — picker endpoint
# ---------------------------------------------------------------------------


def _patch_list_user_repos(return_value):
    return patch(
        "cliff.api.routes.onboarding.GithubClient.list_user_repos",
        new=AsyncMock(return_value=return_value),
    )


async def test_list_repos_returns_picker_options(db_client):
    repos = [
        {
            "full_name": "org/alpha",
            "html_url": "https://github.com/org/alpha",
            "private": True,
            "default_branch": "main",
            "permissions": {"push": True, "pull": True},
            "archived": False,
        },
        {
            "full_name": "org/readonly",
            "html_url": "https://github.com/org/readonly",
            "private": False,
            "default_branch": "main",
            "permissions": {"push": False, "pull": True},
            "archived": False,
        },
        {
            # Archived repos are filtered out — the user can't open a PR
            # against them, picker would just frustrate.
            "full_name": "org/archived",
            "html_url": "https://github.com/org/archived",
            "private": False,
            "default_branch": "main",
            "permissions": {"push": True},
            "archived": True,
        },
    ]
    with _patch_list_user_repos(repos):
        resp = await db_client.post(
            "/api/onboarding/github/repos",
            json={"github_token": "ghp_ok"},
        )
    assert resp.status_code == 200
    body = resp.json()
    names = [r["full_name"] for r in body["repos"]]
    assert names == ["org/alpha", "org/readonly"]  # archived filtered, push first
    assert body["repos"][0]["can_push"] is True
    assert body["repos"][1]["can_push"] is False


async def test_list_repos_401_returns_invalid_token(db_client):
    with _patch_list_user_repos(UnableToVerify(reason="http_401")):
        resp = await db_client.post(
            "/api/onboarding/github/repos",
            json={"github_token": "ghp_bad"},
        )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_token"


async def test_list_repos_empty_token_returns_not_connected(db_client):
    """ADR-0035: an empty/whitespace token now falls through to the vault.
    With nothing in the vault, the route returns ``code=not_connected``
    so the SPA can prompt the user to run /connect first."""
    resp = await db_client.post(
        "/api/onboarding/github/repos",
        json={"github_token": "   "},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "not_connected"


async def test_list_repos_network_failure_returns_502(db_client):
    with _patch_list_user_repos(UnableToVerify(reason="network: TimeoutException")):
        resp = await db_client.post(
            "/api/onboarding/github/repos",
            json={"github_token": "ghp_ok"},
        )
    assert resp.status_code == 502
