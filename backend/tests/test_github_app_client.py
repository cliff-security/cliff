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

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from cliff.integrations.github_app import client as ghapp_client
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


@pytest.fixture(autouse=True)
def _stub_probe_succeeds(monkeypatch):
    """Default the runtime git push probe to "succeeded" for every test in
    this file.

    Why autouse: Q01R-W3 wired ``check_repo_push_access`` to invoke a
    real ``git push --dry-run`` subprocess on every code path that
    previously returned ``can_push=True``. Pre-W3 tests assert the
    API-derived verdict (user perms / install perms shape) and don't care
    about the wire-level probe. Without this stub each of those tests
    would shell out to ``git init``/``git commit``/``git push`` against
    github.com and fail.

    The probe spawns multiple subprocesses (``git init``, ``git commit
    --allow-empty``, then the actual ``git push --dry-run``). All three
    return success here.

    Probe-specific tests below override this with their own monkeypatch.
    """

    class _ProbeOK:
        returncode: int = 0
        killed: bool = False

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return 0

        def kill(self):
            self.killed = True

    async def _fake_exec(*_args, **_kwargs):
        return _ProbeOK()

    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", _fake_exec
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
    # Q01R-W3: success path now annotates the reason with the probe's
    # ``"verified by runtime probe"`` marker rather than leaving it empty,
    # so operators can confirm push access was checked at the wire.
    assert "verified" in result.reason.lower()
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
    # Q01R-W3: success path now annotates the reason with the probe's
    # ``"verified by runtime probe"`` marker rather than leaving it empty,
    # so operators can confirm push access was checked at the wire.
    assert "verified" in result.reason.lower()


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
    # Q01R-W3: success path now annotates the reason with the probe's
    # ``"verified by runtime probe"`` marker rather than leaving it empty,
    # so operators can confirm push access was checked at the wire.
    assert "verified" in result.reason.lower()


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
    # Q01R-W3: success path now annotates the reason with the probe's
    # ``"verified by runtime probe"`` marker rather than leaving it empty,
    # so operators can confirm push access was checked at the wire.
    assert "verified" in result.reason.lower()


# ---------------------------------------------------------------------------
# check_repo_push_access — runtime git push --dry-run probe (Q01R-W3 /
# B37 / IMPL-0019)
#
# All API-derived signals (user perms, install perms) can lie at the
# wire-protocol layer. Wave 3 QA hit the worst case: user-perms fallback
# said push=true, the executor's clone+push then failed at git-push time.
# The probe runs ``git push --dry-run <https-with-token-url>
# HEAD:refs/heads/cliff-push-probe`` from an ephemeral bootstrap repo to
# verify the token can actually push BEFORE we return ``can_push=True``.
# Probe failure downgrades to ``can_push=False`` with a precise reason.
# ---------------------------------------------------------------------------


class _FakeProc:
    """Mimic the slice of asyncio subprocess we use: ``communicate()`` +
    ``returncode``. ``kill()`` is a no-op so the timeout path's cleanup
    doesn't blow up.
    """

    def __init__(
        self,
        *,
        returncode: int,
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self._returncode = returncode
        self._stderr = stderr
        self._hang = hang
        self.returncode: int | None = None
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            # Long enough that the wait_for() wrapper trips its timeout
            # well before this finishes.
            await asyncio.sleep(60)
        self.returncode = self._returncode
        return b"", self._stderr

    async def wait(self) -> int:
        self.returncode = self._returncode
        return self._returncode

    def kill(self) -> None:
        self.killed = True


def _git_subcommand(argv: tuple) -> str | None:
    """Extract the git subcommand from a captured argv tuple.

    ``git -c foo=bar -c baz=qux commit ...`` and ``git push ...`` both
    appear in our subprocess captures. The subcommand is the first
    argv element after ``git`` that isn't a ``-c`` flag (or its value).
    """
    args = list(argv)
    if not args or args[0] != "git":
        return None
    i = 1
    while i < len(args):
        if args[i] == "-c":
            i += 2  # skip the flag value
            continue
        return args[i]
    return None


def _stub_subprocess(proc: _FakeProc):
    """Return an awaitable factory that resolves to ``proc`` for the actual
    ``git push`` call, and to a generic exit-0 stub for the temp-repo
    bootstrap calls (``git init`` and ``git commit --allow-empty``).

    The probe spawns 3 subprocesses in sequence:
      1. ``git init -q`` in the temp dir
      2. ``git commit --allow-empty -q -m probe``
      3. ``git push --dry-run <url> HEAD:refs/heads/cliff-push-probe``

    Tests care about (3) — its argv, its cwd, and its exit. Captured dict
    holds the args/kwargs of the LAST call (the push) plus a ``calls``
    list of all argv tuples (so a regression test can assert the bootstrap
    actually ran).
    """
    captured: dict = {"calls": []}

    class _BootstrapOK:
        returncode: int = 0

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return 0

        def kill(self):  # pragma: no cover — bootstrap never times out
            pass

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["calls"].append(args)
        captured["args"] = args
        captured["kwargs"] = kwargs
        # The git subcommand identifies the call. Bootstrap calls
        # (``init``, ``commit``) get a generic success; the actual
        # probe call (``push``) returns the parameterized ``proc``.
        if _git_subcommand(args) == "push":
            return proc
        return _BootstrapOK()

    return _fake_create_subprocess_exec, captured


@pytest.mark.asyncio
async def test_probe_runs_when_perms_say_push_true_and_succeeds(monkeypatch):
    """User perms say push=true, install perms ok, and the runtime probe
    confirms the token can push at the git protocol layer → can_push=True.
    The probe MUST run — otherwise we regress to the pre-B37 state where
    API signals alone decided the verdict.
    """
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
                "id": 1,
                "permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "metadata": "read",
                },
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    proc = _FakeProc(returncode=0)
    fake_exec, captured = _stub_subprocess(proc)
    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is True
    # The probe must have been invoked exactly with ``git push --dry-run``
    # and a URL that EMBEDS the token (the only way HTTPS git auth works
    # over the protocol). ``git ls-remote --push`` is NOT a valid flag —
    # ``ls-remote`` is read-only. We use ``push --dry-run`` because it
    # performs the full ref-negotiation handshake (where the server
    # enforces push permission) but skips the pack upload.
    assert captured["args"][0] == "git"
    assert captured["args"][1] == "push"
    assert "--dry-run" in captured["args"]
    # The probe pushes a fixed ref so we don't accidentally create branches.
    assert any(
        a == "HEAD:refs/heads/cliff-push-probe" for a in captured["args"]
    )
    # The URL is the second-to-last arg (followed by the refspec).
    url_arg = next(
        a for a in captured["args"] if isinstance(a, str) and a.startswith("https://")
    )
    assert "x-access-token:ghu_test_token_xyz@" in url_arg
    # Bootstrap must have run — ``git init`` then ``git commit`` then the
    # actual push. Without bootstrap, ``git push HEAD:…`` fails with
    # "fatal: not a git repository" from the API server's cwd.
    subcommands = [_git_subcommand(c) for c in captured["calls"]]
    assert "init" in subcommands
    assert "commit" in subcommands
    assert "push" in subcommands
    assert subcommands.index("init") < subcommands.index("push")
    # The push call must have its ``cwd`` set to the bootstrap temp dir,
    # not inherited from the test process.
    assert captured["kwargs"].get("cwd") is not None
    # Success reason is "verified" (canonical reason string per IMPL-0019).
    assert "verified" in result.reason.lower()
    # Reason text must NOT echo the token even when the probe succeeds.
    assert "ghu_test_token_xyz" not in result.reason


@pytest.mark.asyncio
async def test_probe_failure_downgrades_to_can_push_false(monkeypatch):
    """``git push --dry-run`` exits non-zero (permission denied / 403 on
    the wire) → can_push=False, reason mentions credentials/permission.
    This is the B37 path: API signals lie, probe is the ground truth.
    """
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
                "id": 1,
                "permissions": {"contents": "write", "metadata": "read"},
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    proc = _FakeProc(
        returncode=128,
        stderr=(
            b"remote: Permission to cliff-security/NodeGoat.git denied to "
            b"x-access-token.\n"
            b"fatal: unable to access 'https://github.com/...': The "
            b"requested URL returned error: 403\n"
        ),
    )
    fake_exec, _captured = _stub_subprocess(proc)
    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    reason_lower = result.reason.lower()
    assert "credentials" in reason_lower or "permission" in reason_lower
    assert "probe" in reason_lower
    # Reason must NOT echo raw stderr (which may contain remote URL with
    # token embedded) and must NOT include the token directly.
    assert "ghu_test_token_xyz" not in result.reason
    assert "x-access-token" not in result.reason


@pytest.mark.asyncio
async def test_probe_timeout_returns_can_push_false_with_specific_reason(
    monkeypatch,
):
    """``git push --dry-run`` hangs past the configured timeout →
    can_push=False, reason mentions timeout. The probe shouldn't block
    the preflight indefinitely on a stalled DNS or TLS handshake.
    """
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
                "id": 1,
                "permissions": {"contents": "write", "metadata": "read"},
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    proc = _FakeProc(returncode=0, hang=True)
    fake_exec, _captured = _stub_subprocess(proc)
    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
        probe_timeout_seconds=0.05,
    )

    assert result.can_push is False
    reason_lower = result.reason.lower()
    assert "timeout" in reason_lower
    assert "probe" in reason_lower
    # The hung process must have been killed so we don't leak subprocess
    # handles into the event loop on every preflight.
    assert proc.killed is True


@pytest.mark.asyncio
async def test_probe_handles_missing_git_binary_as_failure(monkeypatch):
    """If the ``git`` binary isn't on PATH, spawning the probe raises
    ``FileNotFoundError``. The plan says: fail closed → can_push=False
    with reason "git binary not available". Do NOT raise — preflight is
    a UX surface, an unhandled exception 500s the diagnose endpoint.
    """
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
                "id": 1,
                "permissions": {"contents": "write", "metadata": "read"},
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    async def _fake_exec(*_args, **_kwargs):
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", _fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    assert "git binary not available" in result.reason.lower()


@pytest.mark.asyncio
async def test_probe_failure_overrides_install_lookup_fallback(monkeypatch):
    """The install-lookup-fallback paths (network blip, 403 on
    ``/installation``) historically returned ``can_push=True, reason=""``
    purely on the user-perms signal. The runtime probe must STILL run for
    those paths — they're exactly the paths B37 exploded on. Probe failure
    downgrades the verdict even when the install lookup couldn't fire.
    """
    routes = {
        "/repos/cliff-security/NodeGoat": (
            200,
            {
                "full_name": "cliff-security/NodeGoat",
                "permissions": {"push": True, "pull": True},
            },
        ),
        # 403 here is the most common production path for user OAuth
        # tokens that can't see the App-only /installation endpoint.
        "/repos/cliff-security/NodeGoat/installation": (
            403,
            {"message": "Forbidden"},
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    proc = _FakeProc(returncode=128, stderr=b"remote: Repository not found.\n")
    fake_exec, _captured = _stub_subprocess(proc)
    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    assert result.can_push is False
    reason_lower = result.reason.lower()
    assert "probe" in reason_lower
    # "Repository not found" stderr maps to the not-found reason bucket.
    assert "not found" in reason_lower or "repository" in reason_lower


@pytest.mark.asyncio
async def test_probe_bootstraps_its_own_repo(monkeypatch, tmp_path):
    """Regression: the probe MUST NOT depend on the API server's cwd being a
    git repository.

    Background: ``git push HEAD:refs/heads/cliff-push-probe`` requires a
    local HEAD pointing at a commit. The API server's cwd is generally
    NOT a git repo (and even if it were, we wouldn't want to push from
    it). Without the temp-repo bootstrap (``git init`` + ``git commit
    --allow-empty`` in a ``tempfile.mkdtemp()`` dir), the push would fail
    with ``fatal: not a git repository`` BEFORE ever reaching GitHub, and
    the stderr classifier would (wrongly) bucket it as a credentials
    failure.

    Test: chdir the pytest process into a non-repo directory, mock the
    subprocess to capture the ``cwd`` kwarg each call was invoked with,
    and assert (a) the push call's cwd is NOT the test process's cwd —
    it's a fresh temp dir — and (b) the bootstrap subprocesses ran before
    the push.
    """
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
                "id": 1,
                "permissions": {"contents": "write", "metadata": "read"},
            },
        ),
    }
    transport = httpx.MockTransport(_routed_handler(routes))

    monkeypatch.chdir(tmp_path)  # tmp_path is not a git repo

    proc = _FakeProc(returncode=0)
    fake_exec, captured = _stub_subprocess(proc)
    monkeypatch.setattr(
        ghapp_client.asyncio, "create_subprocess_exec", fake_exec
    )

    result = await check_repo_push_access(
        token="ghu_test_token_xyz",
        owner="cliff-security",
        repo="NodeGoat",
        api_base_url="https://api.example.invalid",
        transport=transport,
    )

    # Probe must complete successfully (not misclassify as auth failure).
    assert result.can_push is True
    assert "verified" in result.reason.lower()

    # Bootstrap ran: init then commit then push, all in the same temp dir.
    subcommands = [_git_subcommand(c) for c in captured["calls"]]
    assert subcommands.count("init") == 1
    assert subcommands.count("commit") == 1
    assert subcommands.count("push") == 1
    assert subcommands.index("init") < subcommands.index("commit")
    assert subcommands.index("commit") < subcommands.index("push")

    # The push call's cwd is the bootstrap temp dir — NOT the test's cwd.
    push_cwd = captured["kwargs"].get("cwd")
    assert push_cwd is not None
    assert str(push_cwd) != str(tmp_path)
    # Bootstrap temp dir is namespaced with ``cliff-push-probe`` prefix.
    assert "cliff-push-probe" in str(push_cwd)


# ---------------------------------------------------------------------------
# Cache invariant: GET /api/integrations/github/diagnose caches per (token,
# repo). The runtime probe verdict must flow into that cache transparently.
# This guards against a regression where the probe runs but the cached
# entry retains the pre-probe (true) verdict.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnose_cache_reflects_probe_verdict(db_client):
    """End-to-end: when the probe says can_push=False, the cached
    PushAccessDiagnoseResponse on a second call must also report False —
    not stale True from a pre-probe lookup. Also verifies the helper is
    invoked exactly once (cache invariant unchanged by the probe wiring).
    """
    from unittest.mock import AsyncMock, patch

    from cliff.main import app

    if hasattr(app.state, "github_diagnose_cache"):
        app.state.github_diagnose_cache = {}

    env_stub = AsyncMock(
        return_value={
            "GH_TOKEN": "ghu_test_token_xyz",
            "CLIFF_REPO_URL": "https://github.com/cliff-security/NodeGoat",
        }
    )

    # Patch ``check_repo_push_access`` at the route's import site to
    # return the probe verdict directly. The route-level cache invariant
    # is what we're testing — the helper's own probe wiring is covered
    # by the tests above. Two calls; the second MUST hit the cache (so
    # the helper is called exactly once) and report the same verdict.
    call_count = {"n": 0}

    async def _mock_check(**_kwargs):
        call_count["n"] += 1
        return RepoPushAccess(
            can_push=False,
            reason="git push probe failed: credentials rejected",
        )

    with (
        patch(
            "cliff.api.routes.github_app._resolve_repo_env_vars",
            new=env_stub,
        ),
        patch(
            "cliff.api.routes.github_app.check_repo_push_access",
            new=_mock_check,
        ),
    ):
        first = await db_client.get("/api/integrations/github/diagnose")
        second = await db_client.get("/api/integrations/github/diagnose")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["can_push"] is False
    assert second.json()["can_push"] is False
    assert first.json()["reason"] == second.json()["reason"]
    # Cache invariant: second call must NOT have re-invoked the helper.
    assert call_count["n"] == 1
    assert "ghu_test_token_xyz" not in first.text
    assert "ghu_test_token_xyz" not in second.text

    if hasattr(app.state, "github_diagnose_cache"):
        app.state.github_diagnose_cache = {}
