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

from cliff.integrations.github_app.client import (
    DeviceCodeResponse,
    GitHubDeviceFlowClient,
    GitHubDeviceFlowError,
    PollTokenResult,
    RepoPushAccess,
    UserInfo,
    check_repo_push_access,
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


# ---------------------------------------------------------------------------
# check_repo_push_access (Q01R / B30 / ADR-0037 / IMPL-0014)
#
# Preflight that verifies the user OAuth token returned by the device flow
# actually has push access to the target repo. The device-flow token's
# effective perms are (App declared perms) intersected with (user repo perms);
# if the App only declares Contents:read the token cannot push regardless of
# what the user can do via gh CLI / a PAT. The fix is to validate up front
# and surface a structured error pointing at the App-permissions doc, rather
# than let the executor "succeed" with an unpushable branch.
# ---------------------------------------------------------------------------


def _push_handler(payload: dict, status: int = 200):
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return _handler


@pytest.mark.asyncio
async def test_check_repo_push_access_returns_can_push_true_when_permission_is_true():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "accept": request.headers.get("accept"),
            }
        )
        return httpx.Response(
            200,
            json={
                "name": "NodeGoat",
                "full_name": "cliff-security/NodeGoat",
                "permissions": {
                    "admin": False,
                    "maintain": False,
                    "push": True,
                    "triage": True,
                    "pull": True,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert isinstance(result, RepoPushAccess)
    assert result.can_push is True
    assert result.reason == ""
    # The first call must be the user-perms endpoint. A second call to
    # ``/installation`` is also issued (Q01R-W2 / B35a) but the handler
    # above shares one response shape between both endpoints — the
    # ``contents`` key is absent, which is the install-perms-fallback
    # signal in client.py.
    assert captured[0]["url"] == (
        "https://api.example.invalid/repos/cliff-security/NodeGoat"
    )
    assert captured[0]["auth"] == "Bearer ghu_abc"
    assert captured[0]["accept"] == "application/vnd.github+json"


@pytest.mark.asyncio
async def test_check_repo_push_access_returns_can_push_false_when_permission_is_false():
    handler = _push_handler(
        {
            "full_name": "cliff-security/NodeGoat",
            "permissions": {
                "admin": False,
                "push": False,
                "pull": True,
            },
        }
    )
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    # Reason must mention App permissions so the UI can tell the user
    # what to actually go fix.
    reason_lower = result.reason.lower()
    assert "push" in reason_lower
    assert "permission" in reason_lower or "app" in reason_lower


@pytest.mark.asyncio
async def test_check_repo_push_access_returns_can_push_false_when_permissions_missing():
    """When the response omits the ``permissions`` block entirely, default
    to *cannot push* — anything else risks blind-firing the executor."""
    handler = _push_handler({"full_name": "cliff-security/NodeGoat"})
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    assert result.reason  # non-empty


@pytest.mark.asyncio
async def test_check_repo_push_access_handles_404_with_clear_reason():
    """A 404 from GitHub means the token can't even see the repo —
    typically the App isn't installed on this org/repo, or the user
    revoked it. Reason text needs to be actionable."""
    handler = _push_handler({"message": "Not Found"}, status=404)
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    assert "not visible" in result.reason.lower() or "404" in result.reason


@pytest.mark.asyncio
async def test_check_repo_push_access_handles_401_with_clear_reason():
    """A 401 means the token is bad/expired — surface that distinctly so
    the UI can prompt re-auth instead of an App permissions update."""
    handler = _push_handler({"message": "Bad credentials"}, status=401)
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_bad",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    reason_lower = result.reason.lower()
    assert (
        "token" in reason_lower
        or "auth" in reason_lower
        or "401" in result.reason
    )


@pytest.mark.asyncio
async def test_check_repo_push_access_fails_open_on_429_rate_limit():
    """A 429 from GitHub during a spike must NOT silently block every
    executor run. The preflight is a UX shortcut, not a correctness
    guarantee — on transient failures we let the executor proceed and
    surface GitHub's real error if the push actually fails."""
    handler = _push_handler({"message": "API rate limit exceeded"}, status=429)
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert "skipped" in result.reason.lower()
    assert "429" in result.reason


@pytest.mark.asyncio
async def test_check_repo_push_access_fails_open_on_5xx():
    """5xx is GitHub having a bad day — same reasoning as 429."""
    handler = _push_handler({"message": "Internal Server Error"}, status=503)
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert "skipped" in result.reason.lower()
    assert "503" in result.reason


@pytest.mark.asyncio
async def test_check_repo_push_access_fails_open_on_network_error():
    """Network/DNS/timeout — same reasoning: don't let a flaky preflight
    become a hard gate."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS lookup failed")

    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert "skipped" in result.reason.lower()
    # Surface the exception class name so logs/metrics can distinguish
    # DNS vs read-timeout vs connection-reset without parsing free text.
    assert "ConnectError" in result.reason


@pytest.mark.asyncio
async def test_check_repo_push_access_does_not_echo_token_in_reason():
    """Defensive: even if GitHub ever reflects the auth header into a
    response body, the reason string must not leak the token. The
    current implementation builds reasons from static strings + the
    parsed status, which is exactly what this test guards."""
    handler = _push_handler(
        {"message": "Reflected: Bearer ghu_secret_token"}, status=403
    )
    transport = httpx.MockTransport(handler)
    result = await check_repo_push_access(
        token="ghu_secret_token",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    assert "ghu_secret_token" not in result.reason
    assert "Bearer" not in result.reason


# ---------------------------------------------------------------------------
# check_repo_push_access — App installation perms (Q01R-W2 / B35a / IMPL-0017)
#
# Even when the user OAuth token reports ``permissions.push=true`` on the
# repo, the App-issued user-to-server token may still fail to push because
# the App's *installation* declares ``contents:read`` — the effective
# write capability is the intersection of (user repo perms) ∩ (App
# installation perms). Preflight needs to consult both surfaces and refuse
# the run when the installation lacks ``contents:write``, with a message
# pointing at the org-admin remediation rather than the user's repo role.
#
# When the ``/installation`` endpoint isn't reachable (e.g. GitHub returns
# 403/404 because the user OAuth token can't call that endpoint), we fall
# back to the legacy user-perms check so the preflight stays useful even
# in environments where install-perm visibility isn't granted to the
# token kind we hold.
# ---------------------------------------------------------------------------


def _routed_handler(routes: dict[str, tuple[int, dict]]):
    """Return a handler that maps URL path -> (status, json_body).

    Keyed by the request path (no host) so callers can express the
    multi-endpoint flow that ``check_repo_push_access`` walks.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path not in routes:
            return httpx.Response(500, json={"message": f"unrouted: {path}"})
        status, payload = routes[path]
        return httpx.Response(status, json=payload)

    return _handler


@pytest.mark.asyncio
async def test_check_uses_install_perms_when_user_says_push_true_but_install_contents_read():
    """User perms say push=true but the App installation only declares
    ``contents:read`` — preflight must surface this BEFORE the executor
    waits 4 minutes to fail at git-push time."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            200,
            {
                "id": 133122855,
                "permissions": {
                    "contents": "read",
                    "metadata": "read",
                    "pull_requests": "read",
                },
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert isinstance(result, RepoPushAccess)
    assert result.can_push is False
    # The reason needs to point at the org-admin remediation (approve the
    # App's newer permissions) rather than the user's repo role.
    reason_lower = result.reason.lower()
    assert "admin" in reason_lower or "approve" in reason_lower
    assert "app" in reason_lower
    # Must not promise a fix the user can do themselves — this requires
    # the org owner to approve the App's updated declared permissions.
    assert "permission" in reason_lower or "contents" in reason_lower


@pytest.mark.asyncio
async def test_check_passes_when_install_perms_contents_write():
    """Belt-and-suspenders: install perms grant contents:write AND user
    perms grant push — preflight returns can_push=True with no reason."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            200,
            {
                "id": 133122855,
                "permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "metadata": "read",
                },
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert result.reason == ""


@pytest.mark.asyncio
async def test_check_falls_back_when_install_lookup_unavailable():
    """User OAuth tokens cannot call the App-only ``/installation``
    endpoint — GitHub returns 404/403 in that case. The preflight must
    fall back to the existing user-perms-only check so we don't regress
    the W1 behavior in environments where the install perms aren't
    visible to the token kind we hold."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            404,
            {"message": "Not Found"},
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    # Falls back to user-perms-only: user push=true → can_push=True.
    assert result.can_push is True


@pytest.mark.asyncio
async def test_check_falls_back_when_install_lookup_returns_403():
    """403 is the more common response for user OAuth tokens calling
    App-only endpoints. Must be treated the same as 404 — fall back to
    the user-perms-only check."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": False, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            403,
            {"message": "Forbidden"},
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    # User perms say push=false → can_push=False with the legacy reason.
    assert result.can_push is False
    assert "push" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_falls_back_when_install_lookup_5xx_or_network():
    """A transient failure on the ``/installation`` lookup must not
    poison the preflight — fall back to the user-perms check so a
    GitHub hiccup on one endpoint doesn't silently block every executor
    run."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            503,
            {"message": "Service unavailable"},
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert result.reason == ""


@pytest.mark.asyncio
async def test_check_install_perms_missing_block_treated_as_fallback():
    """If the ``/installation`` response is 200 but omits the
    ``permissions`` block, treat it like an unavailable lookup and fall
    back to user-perms — don't block on a malformed payload we can't
    interpret."""

    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        "/repos/cliff-security/NodeGoat/installation": (
            200,
            {"id": 1, "account": {"login": "cliff-security"}},
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))
    result = await check_repo_push_access(
        token="ghu_abc",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    assert result.reason == ""
