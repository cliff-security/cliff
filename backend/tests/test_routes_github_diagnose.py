"""Tests for GET /api/integrations/github/diagnose (IMPL-0018, B35c).

This endpoint is the Settings-page push-access badge's data source: a thin
wrapper around :func:`check_repo_push_access` that the Settings card calls
on mount so the user discovers a misconfigured GitHub App *before* they
click Approve and wait for the executor to fail.

The endpoint must:

* Resolve the configured GitHub repo URL the same way the executor
  preflight does (via ``_resolve_repo_env_vars``), so the badge reflects
  exactly what the next executor run would see.
* Surface the result of :func:`check_repo_push_access` *as-is* (the helper
  already returns UI-safe ``reason`` strings — we mustn't re-format or
  echo tokens, headers, or URL path components into the response body).
* Return ``404`` when no enabled GitHub integration is configured. The
  badge renders nothing in that state — there's no point showing a red
  scary message when the user simply hasn't connected GitHub yet.
* Cache the result for 5 minutes on the server side. The Settings page is
  re-rendered routinely (every navigation back to it) and a fresh GitHub
  API call on every render would burn the (low) GitHub-side rate limit
  budget and add a noticeable spinner. ``?refresh=1`` bypasses the cache
  so the user can re-check after fixing the App on github.com.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from cliff.integrations.github_app.client import RepoPushAccess

if TYPE_CHECKING:
    from httpx import AsyncClient


_REPO_URL = "https://github.com/cliff-security/NodeGoat"


@pytest.fixture
def patched_env_vars() -> AsyncMock:
    """Fake out ``_resolve_repo_env_vars`` to return a real-looking token+repo.

    The diagnose route mounts under the same router as the rest of the
    GitHub App routes, but pulls the token+repo via the workspaces helper
    just like the executor preflight does. Faking that helper keeps the
    test focused on the route layer and not on the vault/integration
    plumbing (which has its own coverage)."""
    fn = AsyncMock(
        return_value={
            "GH_TOKEN": "ghu_abc",
            "CLIFF_REPO_URL": _REPO_URL,
        }
    )
    with patch(
        "cliff.api.routes.github_app._resolve_repo_env_vars",
        new=fn,
    ):
        yield fn


@pytest.fixture
def _clear_diagnose_cache():
    """Drop any cached diagnose result between tests.

    The endpoint stores its 5-minute cache on ``app.state``; tests that
    exercise different ``check_repo_push_access`` return values must not
    see a stale verdict from a previous case.
    """
    from cliff.main import app

    if hasattr(app.state, "github_diagnose_cache"):
        app.state.github_diagnose_cache = {}
    yield
    if hasattr(app.state, "github_diagnose_cache"):
        app.state.github_diagnose_cache = {}


@pytest.mark.asyncio
async def test_returns_can_push_true_when_perms_ok(
    db_client: AsyncClient,
    patched_env_vars,  # noqa: ARG001
    _clear_diagnose_cache,  # noqa: ARG001
):
    preflight = AsyncMock(return_value=RepoPushAccess(can_push=True, reason=""))
    with patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        resp = await db_client.get("/api/integrations/github/diagnose")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_push"] is True
    assert body["reason"] == ""
    assert body["repo_url"] == _REPO_URL
    # ISO 8601 — fromisoformat is the cheapest "is this a real timestamp" check.
    from datetime import datetime

    datetime.fromisoformat(body["checked_at"])

    # The endpoint must have called the real check exactly once. If we ever
    # silently swallow the call (e.g. an early-return bug) the badge would
    # show a phantom-green state — exactly the failure mode B35c is trying
    # to surface.
    assert preflight.await_count == 1


@pytest.mark.asyncio
async def test_returns_can_push_false_with_org_admin_message_when_install_perms_insufficient(
    db_client: AsyncClient,
    patched_env_vars,  # noqa: ARG001
    _clear_diagnose_cache,  # noqa: ARG001
):
    """The B35a/B35c case: user has push, App install still on Contents:read.

    The helper returns a sanitized reason naming the remediation
    ("org admin needs to approve") — the route must pass it through
    untouched so the badge can render it verbatim. Re-wrapping or
    truncating the reason would either lose the action verb (and confuse
    the user) or risk leaking attacker-supplied URL fragments.
    """
    reason = (
        "The Cliff GitHub App's installation on cliff-security/NodeGoat "
        "declares Contents:read, not Contents:write. An org admin needs "
        "to approve the App's updated permissions before pushes can "
        "succeed — open the App in GitHub's org settings and click "
        "“Review request” to approve the new permissions."
    )
    preflight = AsyncMock(
        return_value=RepoPushAccess(can_push=False, reason=reason)
    )
    with patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        resp = await db_client.get("/api/integrations/github/diagnose")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_push"] is False
    assert body["reason"] == reason
    # The "what should the user do" verb must survive. We assert on a
    # token from the canonical helper reason rather than a fuzzy match,
    # so renaming the message in client.py still flags this test.
    assert "admin" in body["reason"].lower()
    assert body["repo_url"] == _REPO_URL


@pytest.mark.asyncio
async def test_returns_404_when_github_not_configured(
    db_client: AsyncClient,
    _clear_diagnose_cache,  # noqa: ARG001
):
    """No GitHub integration → 404 with a short, non-leaky detail string.

    The badge renders nothing on 404. Importantly we must NOT call
    ``check_repo_push_access`` here — there's no token to call it with —
    and we must NOT echo any repo URL in the response body (there isn't
    one to echo, but it's worth pinning the contract).
    """
    # Empty env-vars means no GH_TOKEN, no CLIFF_REPO_URL. Mirrors the
    # "user hasn't connected GitHub yet" state.
    empty_env = AsyncMock(return_value={})
    preflight = AsyncMock(
        return_value=RepoPushAccess(can_push=True, reason="")
    )
    with patch(
        "cliff.api.routes.github_app._resolve_repo_env_vars",
        new=empty_env,
    ), patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        resp = await db_client.get("/api/integrations/github/diagnose")

    assert resp.status_code == 404, resp.text
    assert "github" in resp.json()["detail"].lower()
    assert preflight.await_count == 0


@pytest.mark.asyncio
async def test_caches_result_within_window(
    db_client: AsyncClient,
    patched_env_vars,  # noqa: ARG001
    _clear_diagnose_cache,  # noqa: ARG001
):
    """Two diagnose calls in quick succession must hit GitHub at most once.

    This is the rate-limit protection called out in IMPL-0018's Risk
    section. If we ever regress and call the helper on every request the
    Settings page (which re-mounts on navigate-back) could blow through
    the user's API budget in a busy day.
    """
    preflight = AsyncMock(return_value=RepoPushAccess(can_push=True, reason=""))
    with patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        first = await db_client.get("/api/integrations/github/diagnose")
        second = await db_client.get("/api/integrations/github/diagnose")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert preflight.await_count == 1


@pytest.mark.asyncio
async def test_refresh_bypasses_cache(
    db_client: AsyncClient,
    patched_env_vars,  # noqa: ARG001
    _clear_diagnose_cache,  # noqa: ARG001
):
    """``?refresh=1`` must force a fresh GitHub call.

    Without this affordance the user has no way to re-verify after they
    fix the App on github.com — the badge would stay red until the cache
    naturally expires (~5 min) which the user reads as "Cliff didn't
    notice".
    """
    preflight = AsyncMock(return_value=RepoPushAccess(can_push=True, reason=""))
    with patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        await db_client.get("/api/integrations/github/diagnose")
        await db_client.get("/api/integrations/github/diagnose?refresh=1")

    assert preflight.await_count == 2


@pytest.mark.asyncio
async def test_cache_key_includes_repo_url(
    db_client: AsyncClient,
    _clear_diagnose_cache,  # noqa: ARG001
):
    """Reconnecting to a different repo must invalidate the cached verdict.

    Hard rule from the task brief: if the user disconnects the GitHub
    App and reconnects pointing at a different org/repo, the badge must
    reflect the *new* repo immediately — not last hour's verdict for the
    previous one. We simulate that by patching the env-var resolver to
    return a different ``CLIFF_REPO_URL`` between two calls.
    """
    preflight = AsyncMock(return_value=RepoPushAccess(can_push=True, reason=""))

    first_env = AsyncMock(
        return_value={"GH_TOKEN": "ghu_abc", "CLIFF_REPO_URL": _REPO_URL}
    )
    other_repo = "https://github.com/other-org/other-repo"
    second_env = AsyncMock(
        return_value={"GH_TOKEN": "ghu_abc", "CLIFF_REPO_URL": other_repo}
    )

    with patch(
        "cliff.api.routes.github_app.check_repo_push_access",
        new=preflight,
    ):
        with patch(
            "cliff.api.routes.github_app._resolve_repo_env_vars",
            new=first_env,
        ):
            first = await db_client.get("/api/integrations/github/diagnose")
        with patch(
            "cliff.api.routes.github_app._resolve_repo_env_vars",
            new=second_env,
        ):
            second = await db_client.get("/api/integrations/github/diagnose")

    assert first.json()["repo_url"] == _REPO_URL
    assert second.json()["repo_url"] == other_repo
    # Two distinct cache keys → two underlying calls.
    assert preflight.await_count == 2
