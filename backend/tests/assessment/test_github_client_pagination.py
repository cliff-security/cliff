"""Tests for the GithubClient pagination helpers added for the onboarding picker."""

from __future__ import annotations

import httpx
import pytest

from cliff.assessment.posture.github_client import (
    GithubClient,
    UnableToVerify,
    _parse_next_link,
)


def test_parse_next_link_extracts_next_url():
    header = (
        '<https://api.github.com/user/repos?page=2>; rel="next", '
        '<https://api.github.com/user/repos?page=5>; rel="last"'
    )
    assert _parse_next_link(header) == "https://api.github.com/user/repos?page=2"


def test_parse_next_link_returns_none_when_no_next():
    header = '<https://api.github.com/user/repos?page=1>; rel="prev"'
    assert _parse_next_link(header) is None


def test_parse_next_link_handles_missing_header():
    assert _parse_next_link(None) is None
    assert _parse_next_link("") is None


@pytest.mark.asyncio
async def test_list_user_repos_follows_pagination_to_max_pages():
    """``max_pages`` caps how deep we walk so accounts with thousands of
    repos don't time out the picker — we expose a manual-URL fallback
    instead.
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        page = int(request.url.params.get("page", "1"))
        # Always advertise a next page so we exercise the cap.
        next_link = (
            f'<https://api.github.com/user/repos?page={page + 1}>; rel="next"'
        )
        return httpx.Response(
            200,
            json=[{"full_name": f"org/repo-{page}-{i}"} for i in range(2)],
            headers={"Link": next_link},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(http, token="ghp_x")
        result = await client.list_user_repos(max_pages=3, per_page=2)

    assert isinstance(result, list)
    assert len(result) == 6  # 3 pages * 2 repos
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_list_user_repos_stops_when_no_next_link():
    def handler(request: httpx.Request) -> httpx.Response:
        # No Link header → only one page.
        return httpx.Response(200, json=[{"full_name": "org/only"}])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(http, token="ghp_x")
        result = await client.list_user_repos(max_pages=5)

    assert isinstance(result, list)
    assert [r["full_name"] for r in result] == ["org/only"]


@pytest.mark.asyncio
async def test_list_user_repos_returns_unable_to_verify_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GithubClient(http, token="ghp_bad")
        result = await client.list_user_repos()

    assert result == UnableToVerify(reason="http_401")
