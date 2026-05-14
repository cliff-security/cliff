"""Tests for the agent reference verifier (Q01-B08)."""

from __future__ import annotations

import httpx
import pytest

from opensec.services.reference_verifier import ReferenceCheck, clean_references


def _client(handler) -> httpx.AsyncClient:
    """An AsyncClient backed by a MockTransport calling *handler*."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Sanitize pass — deterministic, no network
# ---------------------------------------------------------------------------


async def test_drops_non_ascii_url() -> None:
    """The exact B08 case: Cyrillic glyphs jammed into a commit SHA."""
    bad = (
        "https://github.com/substack/minimist/commit/"
        "38a4d1caead72ef99e824bb4237902циклерок"
    )
    check = await clean_references([bad], http=_client(lambda r: httpx.Response(200)))
    assert check.kept == []
    assert check.dropped == [(bad, "non_ascii")]


async def test_drops_malformed_commit_sha() -> None:
    bad = "https://github.com/substack/minimist/commit/not-a-real-sha"
    check = await clean_references([bad], http=_client(lambda r: httpx.Response(200)))
    assert check.kept == []
    assert check.dropped[0][1] == "malformed_commit_sha"


async def test_keeps_well_formed_commit_sha() -> None:
    good = "https://github.com/substack/minimist/commit/38a4d1caead72ef99e824bb4237902abcdef1234"
    check = await clean_references([good], http=_client(lambda r: httpx.Response(200)))
    assert check.kept == [good]


async def test_drops_non_http_scheme() -> None:
    check = await clean_references(
        ["ftp://example.com/x", "javascript:alert(1)"],
        http=_client(lambda r: httpx.Response(200)),
    )
    assert check.kept == []
    assert {reason for _, reason in check.dropped} == {"not_http_url"}


# ---------------------------------------------------------------------------
# Verify pass — network, best-effort
# ---------------------------------------------------------------------------


async def test_drops_404() -> None:
    """The other B08 case: a structurally-valid GHSA URL that 404s."""
    ghsa = "https://github.com/advisories/GHSA-xvch-5gc4-4984"
    check = await clean_references(
        [ghsa], http=_client(lambda r: httpx.Response(404))
    )
    assert check.kept == []
    assert check.dropped == [(ghsa, "http_404")]


async def test_keeps_200() -> None:
    url = "https://nvd.nist.gov/vuln/detail/CVE-2021-44906"
    check = await clean_references(
        [url], http=_client(lambda r: httpx.Response(200))
    )
    assert check.kept == [url]


@pytest.mark.parametrize("status", [301, 403, 429, 500, 503])
async def test_keeps_ambiguous_statuses(status: int) -> None:
    """Only a definitive 404/410 drops a reference — never punish a flaky
    probe (redirects, auth walls, rate limits, server errors)."""
    url = "https://example.com/advisory"
    check = await clean_references(
        [url], http=_client(lambda r: httpx.Response(status))
    )
    assert check.kept == [url]


async def test_keeps_on_network_error() -> None:
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    url = "https://example.com/advisory"
    check = await clean_references([url], http=_client(_boom))
    assert check.kept == [url]


# ---------------------------------------------------------------------------
# Input hygiene
# ---------------------------------------------------------------------------


async def test_non_list_input_is_empty() -> None:
    for bad in (None, "https://example.com", 42, {"a": 1}):
        check = await clean_references(bad)
        assert check == ReferenceCheck()


async def test_dedupes_before_probing() -> None:
    url = "https://example.com/x"
    check = await clean_references(
        [url, url], http=_client(lambda r: httpx.Response(200))
    )
    assert check.kept == [url]


# ---------------------------------------------------------------------------
# Full B08 repro — the F-001 minimist reference list
# ---------------------------------------------------------------------------


async def test_b08_minimist_reference_list() -> None:
    """Two fabricated refs (Cyrillic commit URL + 404 GHSA) are dropped; the
    real NVD link survives."""
    nvd = "https://nvd.nist.gov/vuln/detail/CVE-2021-44906"
    cyrillic = (
        "https://github.com/substack/minimist/commit/"
        "38a4d1caead72ef99e824bb4237902циклерок"
    )
    ghsa = "https://github.com/advisories/GHSA-xvch-5gc4-4984"

    def _handler(request: httpx.Request) -> httpx.Response:
        # github.com/advisories/<fake> 404s; everything else resolves.
        if "GHSA-xvch-5gc4-4984" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200)

    check = await clean_references([nvd, cyrillic, ghsa], http=_client(_handler))
    assert check.kept == [nvd]
    assert {reason for _, reason in check.dropped} == {"non_ascii", "http_404"}
