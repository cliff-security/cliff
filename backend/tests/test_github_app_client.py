"""Tests for GitHubDeviceFlowClient (IMPL-0010, Phase 2).

The client is a thin wrapper around the three GitHub endpoints that
participate in the device flow:

- POST /login/device/code           (oauth host)
- POST /login/oauth/access_token    (oauth host)
- GET  /user                        (api host)

We never touch the real network — every test injects an
``httpx.MockTransport`` so we can assert request shape and exercise every
documented response.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from opensec.integrations.github_app.client import (
    DeviceCodeResponse,
    GitHubDeviceFlowClient,
    GitHubDeviceFlowError,
    PollTokenResult,
    UserInfo,
)


def _client_with_handler(
    handler,
    *,
    api_base: str = "https://api.example.invalid",
    oauth_base: str = "https://oauth.example.invalid",
) -> GitHubDeviceFlowClient:
    transport = httpx.MockTransport(handler)
    return GitHubDeviceFlowClient(
        client_id="Iv23liTestId",
        api_base_url=api_base,
        oauth_base_url=oauth_base,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# request_device_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_device_code_returns_parsed_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["accept"] = request.headers.get("accept")
        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "device_code": "DEVICE-XYZ",
                "user_code": "WDJB-MJHT",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
        )

    client = _client_with_handler(handler)
    result = await client.request_device_code()

    assert isinstance(result, DeviceCodeResponse)
    assert result.device_code == "DEVICE-XYZ"
    assert result.user_code == "WDJB-MJHT"
    assert result.verification_uri == "https://github.com/login/device"
    assert result.expires_in == 900
    assert result.interval == 5

    assert captured["url"] == "https://oauth.example.invalid/login/device/code"
    assert captured["method"] == "POST"
    assert captured["accept"] == "application/json"
    assert captured["body"]["client_id"] == ["Iv23liTestId"]


@pytest.mark.asyncio
async def test_request_device_code_raises_on_429_rate_limit():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "rate limited"})

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError) as exc:
        await client.request_device_code()
    assert "429" in str(exc.value) or "rate" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_request_device_code_raises_on_unexpected_payload():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError):
        await client.request_device_code()


# ---------------------------------------------------------------------------
# poll_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_token_returns_access_token_on_success():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "ghu_abcdef",
                "token_type": "bearer",
                "scope": "",
            },
        )

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert isinstance(result, PollTokenResult)
    assert result.kind == "success"
    assert result.access_token == "ghu_abcdef"
    assert result.refresh_token is None
    assert result.expires_in is None

    assert captured["body"]["client_id"] == ["Iv23liTestId"]
    assert captured["body"]["device_code"] == ["DEV-1"]
    assert captured["body"]["grant_type"] == [
        "urn:ietf:params:oauth:grant-type:device_code"
    ]


@pytest.mark.asyncio
async def test_poll_token_returns_access_token_with_refresh_when_expiry_enabled():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "ghu_main",
                "expires_in": 28800,
                "refresh_token": "ghr_refresh",
                "refresh_token_expires_in": 15897600,
                "token_type": "bearer",
                "scope": "",
            },
        )

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert result.kind == "success"
    assert result.access_token == "ghu_main"
    assert result.refresh_token == "ghr_refresh"
    assert result.expires_in == 28800


@pytest.mark.asyncio
async def test_poll_token_returns_pending_on_authorization_pending():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "authorization_pending"})

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert result.kind == "authorization_pending"
    assert result.access_token is None


@pytest.mark.asyncio
async def test_poll_token_returns_slow_down_when_rate_limited():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "slow_down", "interval": 10}
        )

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert result.kind == "slow_down"
    assert result.interval == 10


@pytest.mark.asyncio
async def test_poll_token_returns_expired_when_token_expired():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "expired_token"})

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert result.kind == "expired_token"


@pytest.mark.asyncio
async def test_poll_token_returns_denied_on_access_denied():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "access_denied"})

    client = _client_with_handler(handler)
    result = await client.poll_token(device_code="DEV-1")

    assert result.kind == "access_denied"


@pytest.mark.asyncio
async def test_poll_token_raises_on_unknown_github_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": "incorrect_client_credentials"},
        )

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError) as exc:
        await client.poll_token(device_code="DEV-1")
    assert "incorrect_client_credentials" in str(exc.value)


@pytest.mark.asyncio
async def test_poll_token_raises_on_429():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "secondary rate limit"})

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError):
        await client.poll_token(device_code="DEV-1")


# ---------------------------------------------------------------------------
# fetch_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_user_returns_login_and_id():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"login": "octocat", "id": 1, "name": "The Octocat"},
        )

    client = _client_with_handler(handler)
    result = await client.fetch_user(access_token="ghu_test")

    assert isinstance(result, UserInfo)
    assert result.login == "octocat"
    assert result.id == 1

    assert captured["url"] == "https://api.example.invalid/user"
    assert captured["auth"] == "Bearer ghu_test"


@pytest.mark.asyncio
async def test_fetch_user_raises_on_401():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError):
        await client.fetch_user(access_token="bad")


# ---------------------------------------------------------------------------
# refresh_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_returns_new_tokens():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "ghu_new",
                "expires_in": 28800,
                "refresh_token": "ghr_new",
                "token_type": "bearer",
            },
        )

    client = _client_with_handler(handler)
    result = await client.refresh_access_token(refresh_token="ghr_old")

    assert result.kind == "success"
    assert result.access_token == "ghu_new"
    assert result.refresh_token == "ghr_new"
    assert captured["body"]["grant_type"] == ["refresh_token"]
    assert captured["body"]["refresh_token"] == ["ghr_old"]
    assert captured["body"]["client_id"] == ["Iv23liTestId"]


@pytest.mark.asyncio
async def test_refresh_token_returns_error_kind_on_invalid_grant():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_refresh_token"})

    client = _client_with_handler(handler)
    with pytest.raises(GitHubDeviceFlowError):
        await client.refresh_access_token(refresh_token="bad")
