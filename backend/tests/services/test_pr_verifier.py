"""Tests for ``cliff.services.pr_verifier`` — the B16 guardrail.

Design intent: every failure mode the LLM can produce should collapse into a
non-raising ``PRVerification(ok=False, reason=...)`` with a reason tag an
operator can scan quickly. The happy path must also verify that the PR
number echoed back by GitHub matches the number in the URL — a redirect on
a renamed repo would otherwise sneak a different PR through.
"""

from __future__ import annotations

import httpx
import pytest

from cliff.services.pr_verifier import (
    parse_pr_url,
    verify_pr_url,
)


class TestParsePrUrl:
    def test_canonical_url(self) -> None:
        parsed = parse_pr_url("https://github.com/acme/widget/pull/42")
        assert parsed is not None
        assert parsed.owner == "acme"
        assert parsed.repo == "widget"
        assert parsed.number == 42

    def test_trailing_slash_ok(self) -> None:
        parsed = parse_pr_url("https://github.com/a/b/pull/1/")
        assert parsed is not None
        assert parsed.number == 1

    def test_dot_in_repo_name(self) -> None:
        # Forks like ``my.org/some.repo`` are allowed by GitHub.
        parsed = parse_pr_url("https://github.com/my.org/some.repo/pull/7")
        assert parsed is not None
        assert parsed.repo == "some.repo"

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "not a url",
            # Compare page — the shape the agent hallucinated in dogfooding.
            "https://github.com/acme/widget/pull/new/cliff-fix",
            # Tree/commit views dressed up to look like PRs.
            "https://github.com/acme/widget/tree/cliff-fix",
            "https://github.com/acme/widget/pulls",
            # Other hosts should be rejected even if they mirror GitHub's shape.
            "https://gitlab.com/acme/widget/pull/1",
            # Query strings / fragments — agent sometimes adds tracking.
            "https://github.com/acme/widget/pull/1?diff=unified",
            "https://github.com/acme/widget/pull/1#diff",
            # Zero or non-numeric PR numbers.
            "https://github.com/acme/widget/pull/0",
            "https://github.com/acme/widget/pull/abc",
        ],
    )
    def test_rejects_non_canonical(self, url: str | None) -> None:
        assert parse_pr_url(url) is None


def _client_for(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


class TestVerifyPrUrl:
    @pytest.mark.asyncio
    async def test_verified_when_github_returns_matching_pr(self) -> None:
        called: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            called["url"] = str(request.url)
            called["auth"] = request.headers.get("Authorization", "")
            return httpx.Response(
                200,
                json={
                    "number": 42,
                    "state": "open",
                    "merged": False,
                    "html_url": "https://github.com/acme/widget/pull/42",
                },
            )

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/acme/widget/pull/42",
                token="ghp_test",
                http=client,
            )

        assert result.ok is True
        assert result.pr_state == "open"
        assert result.html_url == "https://github.com/acme/widget/pull/42"
        assert called["url"].endswith("/repos/acme/widget/pulls/42")
        assert called["auth"] == "Bearer ghp_test"

    @pytest.mark.asyncio
    async def test_merged_pr_is_ok_with_merged_state(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "number": 9,
                    "state": "closed",
                    "merged": True,
                    "html_url": "https://github.com/a/b/pull/9",
                },
            )

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/a/b/pull/9", token=None, http=client
            )

        assert result.ok is True
        assert result.pr_state == "merged"

    @pytest.mark.asyncio
    async def test_invalid_url_never_touches_network(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            pytest.fail("network should not be called for invalid URL")

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/acme/widget/pull/new/branch",
                token="ghp_test",
                http=client,
            )

        assert result.ok is False
        assert result.reason.startswith("not_a_pull_url: ")

    @pytest.mark.asyncio
    async def test_none_url_is_rejected(self) -> None:
        result = await verify_pr_url(None, token=None)
        assert result.ok is False
        assert "not_a_pull_url" in result.reason

    @pytest.mark.asyncio
    async def test_404_maps_to_not_found(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/acme/widget/pull/99",
                token="ghp_test",
                http=client,
            )

        assert result.ok is False
        assert result.reason.startswith("not_found:")

    @pytest.mark.asyncio
    async def test_403_maps_to_auth_failure(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "forbidden"})

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/acme/widget/pull/1",
                token="bad",
                http=client,
            )

        assert result.ok is False
        assert result.reason.startswith("http_403:")

    @pytest.mark.asyncio
    async def test_mismatched_pr_number_rejected(self) -> None:
        # GitHub occasionally redirects PR lookups when a repo is renamed
        # and the response lands on a different PR entirely.
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "number": 7,  # agent claimed 42
                    "state": "open",
                    "merged": False,
                    "html_url": "https://github.com/other/repo/pull/7",
                },
            )

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/acme/widget/pull/42",
                token="ghp_test",
                http=client,
            )

        assert result.ok is False
        assert result.reason == "http_200_but_pr_mismatch"

    @pytest.mark.asyncio
    async def test_network_error_collapses_to_ok_false(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure")

        async with _client_for(handler) as client:
            result = await verify_pr_url(
                "https://github.com/a/b/pull/1",
                token=None,
                http=client,
            )

        assert result.ok is False
        assert result.reason.startswith("network:")
