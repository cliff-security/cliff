"""Thin async HTTP client for GitHub's three device-flow endpoints (IMPL-0010).

Stateless. The caller supplies the ``client_id`` (public). Base URLs are
overridable so tests use ``httpx.MockTransport`` and don't touch the real
network. The wrapper does **no** retry / backoff — that's the orchestrator's
job (Phase 3).

Reference:
https://docs.github.com/en/apps/creating-github-apps/writing-code-with-the-rest-api/using-the-device-flow-to-generate-a-user-access-token-for-a-github-app
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

DEVICE_CODE_PATH = "/login/device/code"
TOKEN_PATH = "/login/oauth/access_token"  # noqa: S105 — URL path, not a credential
USER_PATH = "/user"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class GitHubDeviceFlowError(RuntimeError):
    """Unexpected response from GitHub during the device flow."""


class GitHubDeviceFlowTransientError(GitHubDeviceFlowError):
    """Subset of :class:`GitHubDeviceFlowError` for recoverable failures
    (HTTP 429 / 5xx). The orchestrator retries on next poll tick rather
    than marking the row terminal."""


# Errors the orchestrator should treat as transient — retry on next
# tick rather than marking the row terminal. Defined here next to the
# raising classes so the contract lives in one place; the orchestrator
# just imports and uses the tuple.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,  # superclass of ConnectError, ReadError, WriteError
    httpx.RemoteProtocolError,
    GitHubDeviceFlowTransientError,
)


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


PollKind = Literal[
    "success",
    "authorization_pending",
    "slow_down",
    "expired_token",
    "access_denied",
]


@dataclass(frozen=True)
class PollTokenResult:
    kind: PollKind
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    interval: int | None = None  # populated only on slow_down


@dataclass(frozen=True)
class UserInfo:
    login: str
    id: int


class GitHubDeviceFlowClient:
    """Async wrapper around GitHub's device-flow endpoints.

    The transport can be overridden (httpx.MockTransport in tests). When
    ``transport`` is provided, the client owns its own ``AsyncClient`` and
    closes it on ``aclose()``. In production we hand-build an AsyncClient
    on each call so the orchestrator's lifetime isn't tied to ours - the
    flow is short-lived.
    """

    def __init__(
        self,
        *,
        client_id: str,
        api_base_url: str = "https://api.github.com",
        oauth_base_url: str = "https://github.com",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._api_base = api_base_url.rstrip("/")
        self._oauth_base = oauth_base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def _async_client(self) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def request_device_code(self) -> DeviceCodeResponse:
        """POST /login/device/code — returns the device + user codes."""
        url = f"{self._oauth_base}{DEVICE_CODE_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={"client_id": self._client_id},
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"device_code request failed: HTTP {resp.status_code} {resp.text}"
            )
        body = resp.json()
        try:
            return DeviceCodeResponse(
                device_code=body["device_code"],
                user_code=body["user_code"],
                verification_uri=body["verification_uri"],
                expires_in=int(body["expires_in"]),
                interval=int(body["interval"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubDeviceFlowError(
                f"device_code response missing fields: {body}"
            ) from exc

    async def poll_token(self, *, device_code: str) -> PollTokenResult:
        """POST /login/oauth/access_token — one polling attempt."""
        url = f"{self._oauth_base}{TOKEN_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={
                    "client_id": self._client_id,
                    "device_code": device_code,
                    "grant_type": DEVICE_CODE_GRANT,
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise GitHubDeviceFlowTransientError(
                    f"token poll transient: HTTP {resp.status_code} {resp.text}"
                )
            raise GitHubDeviceFlowError(
                f"token poll failed: HTTP {resp.status_code} {resp.text}"
            )
        body = resp.json()

        if "access_token" in body:
            return PollTokenResult(
                kind="success",
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token"),
                expires_in=body.get("expires_in"),
            )

        error = body.get("error")
        if error == "authorization_pending":
            return PollTokenResult(kind="authorization_pending")
        if error == "slow_down":
            return PollTokenResult(
                kind="slow_down", interval=body.get("interval")
            )
        if error == "expired_token":
            return PollTokenResult(kind="expired_token")
        if error == "access_denied":
            return PollTokenResult(kind="access_denied")
        raise GitHubDeviceFlowError(
            f"unexpected token poll error: {error or body!r}"
        )

    async def refresh_access_token(self, *, refresh_token: str) -> PollTokenResult:
        """POST /login/oauth/access_token with grant_type=refresh_token.

        Returned shape mirrors :meth:`poll_token` so callers can treat
        ``kind=='success'`` uniformly. Anything other than success raises -
        the orchestrator marks the integration ``needs_reconnect`` from
        the exception in Phase 5.
        """
        url = f"{self._oauth_base}{TOKEN_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"refresh failed: HTTP {resp.status_code} {resp.text}"
            )
        body = resp.json()
        if "access_token" in body:
            return PollTokenResult(
                kind="success",
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token"),
                expires_in=body.get("expires_in"),
            )
        raise GitHubDeviceFlowError(
            f"refresh response missing access_token: {body!r}"
        )

    async def fetch_user(self, *, access_token: str) -> UserInfo:
        """GET /user — used to record the github_login post-connect."""
        url = f"{self._api_base}{USER_PATH}"
        async with self._async_client() as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"GET /user failed: HTTP {resp.status_code} {resp.text}"
            )
        body = resp.json()
        try:
            return UserInfo(login=body["login"], id=int(body["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubDeviceFlowError(
                f"GET /user response missing fields: {body!r}"
            ) from exc
