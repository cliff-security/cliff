"""Collaborator-hygiene posture checks (Epic 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from opensec.assessment.posture import RepoCoords
from opensec.assessment.posture.collaborator_hygiene import (
    STALE_DAYS,
    check_broad_team_permissions,
    check_default_branch_permissions,
    check_stale_collaborators,
)
from opensec.assessment.posture.github_client import UnableToVerify


class _StubClient:
    def __init__(self, **stubs: Any) -> None:
        self._stubs = stubs

    def __getattr__(self, name: str) -> Any:
        if name not in self._stubs:
            raise AttributeError(name)

        async def _call(*_args: Any, **_kw: Any) -> Any:
            return self._stubs[name]

        return _call


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace(
        "+00:00", "Z"
    )


@pytest.mark.asyncio
async def test_stale_collaborators_pass_when_all_recent() -> None:
    client = _StubClient(
        list_collaborators=[
            {
                "login": "alice",
                "permissions": {"push": True},
                "last_active": _iso(days_ago=5),
            },
            {
                "login": "bob",
                "permissions": {"admin": True},
                "last_active": _iso(days_ago=30),
            },
        ]
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "pass"
    assert result.detail["threshold_days"] == STALE_DAYS


@pytest.mark.asyncio
async def test_stale_collaborators_fail_above_90_days() -> None:
    client = _StubClient(
        list_collaborators=[
            {
                "login": "alice",
                "permissions": {"push": True},
                "last_active": _iso(days_ago=200),
            },
            {
                "login": "bob",
                "permissions": {"admin": True},
                "last_active": _iso(days_ago=10),
            },
        ]
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "fail"
    assert result.detail["stale_count"] == 1
    assert result.detail["stale"][0]["login"] == "alice"


@pytest.mark.asyncio
async def test_stale_collaborators_excludes_read_only_users() -> None:
    """Pull-only collaborators don't pose the same risk; ignore them."""
    client = _StubClient(
        list_collaborators=[
            {
                "login": "alice",
                "permissions": {"pull": True},
                "last_active": _iso(days_ago=400),
            }
        ]
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_stale_collaborators_unknown_on_pat_failure() -> None:
    client = _StubClient(list_collaborators=UnableToVerify(reason="http_403"))
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "unknown"
    assert result.detail == {"reason": "http_403"}


@pytest.mark.asyncio
async def test_stale_collaborators_uses_user_events_fallback() -> None:
    """When /collaborators omits last_active (the real GitHub shape), the check
    falls back to /users/{login}/events for each push/admin collaborator and
    uses the most recent public event as the activity signal.
    """
    client = _StubClient(
        list_collaborators=[
            {
                "login": "galanko",
                "permissions": {"admin": True, "push": True},
                # No last_active / last_activity_at — mirrors the real API.
            }
        ],
        get_user_last_event=_iso(days_ago=3),
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "pass"
    assert result.detail["eligible"] == 1
    assert "stale" not in result.detail


@pytest.mark.asyncio
async def test_stale_collaborators_fail_via_events_fallback() -> None:
    """If /users/{login}/events returns a timestamp older than the cutoff,
    the collaborator is correctly flagged as stale via the fallback path."""
    client = _StubClient(
        list_collaborators=[
            {
                "login": "galanko",
                "permissions": {"admin": True, "push": True},
            }
        ],
        get_user_last_event=_iso(days_ago=400),
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "fail"
    assert result.detail["stale_count"] == 1
    assert result.detail["stale"][0]["login"] == "galanko"


@pytest.mark.asyncio
async def test_stale_collaborators_pass_when_events_unverifiable() -> None:
    """A collaborator whose events endpoint returns 404 or no entries should
    NOT be auto-flagged as stale — they may simply have no public footprint
    (private-repo-only contributors). Record as unverifiable, pass the check.
    """
    client = _StubClient(
        list_collaborators=[
            {
                "login": "private-user",
                "permissions": {"push": True},
            }
        ],
        get_user_last_event=None,
    )
    result = await check_stale_collaborators(client, RepoCoords(owner="o", repo="r"))
    assert result.status == "pass"
    assert result.detail["unverifiable"] == ["private-user"]


@pytest.mark.asyncio
async def test_broad_team_permissions_advisory_with_no_method_available() -> None:
    """When the client doesn't support list_repo_teams, degrade to unknown."""
    client = _StubClient()
    result = await check_broad_team_permissions(
        client, RepoCoords(owner="o", repo="r")
    )
    assert result.status == "unknown"


@pytest.mark.asyncio
async def test_broad_team_permissions_advisory_when_supported() -> None:
    client = _StubClient(
        list_repo_teams=[
            {"slug": "core", "permission": "push", "members_count": 30},
            {"slug": "viewers", "permission": "pull", "members_count": 100},
        ]
    )
    result = await check_broad_team_permissions(
        client, RepoCoords(owner="o", repo="r")
    )
    assert result.status == "advisory"
    assert result.detail["flagged_count"] == 1


@pytest.mark.asyncio
async def test_broad_team_permissions_pass_when_no_teams_flagged() -> None:
    """No write-access teams over the threshold → emit pass, not advisory.

    Without this, the row sat perpetually open on the Issues page even though
    nothing was actionable.
    """
    client = _StubClient(
        list_repo_teams=[
            {"slug": "viewers", "permission": "pull", "members_count": 100},
        ]
    )
    result = await check_broad_team_permissions(
        client, RepoCoords(owner="o", repo="r")
    )
    assert result.status == "pass"
    assert result.detail["flagged_count"] == 0


@pytest.mark.asyncio
async def test_default_branch_permissions_pass_when_protected() -> None:
    client = _StubClient(
        get_repo_info={"default_branch": "main"},
        get_branch_protection={"required_status_checks": {}},
    )
    result = await check_default_branch_permissions(
        client, RepoCoords(owner="o", repo="r")
    )
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_default_branch_permissions_fail_when_no_rule() -> None:
    client = _StubClient(
        get_repo_info={"default_branch": "main"},
        get_branch_protection=None,
    )
    result = await check_default_branch_permissions(
        client, RepoCoords(owner="o", repo="r")
    )
    assert result.status == "fail"
