"""Thin async HTTP client for GitHub's three device-flow endpoints (IMPL-0010).

Stateless. The caller supplies the ``client_id`` (public). Base URLs are
overridable so tests use ``httpx.MockTransport`` and don't touch the real
network. The wrapper does **no** retry / backoff — that's the orchestrator's
job (Phase 3).

Reference:
https://docs.github.com/en/apps/creating-github-apps/writing-code-with-the-rest-api/using-the-device-flow-to-generate-a-user-access-token-for-a-github-app
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import httpx

DEVICE_CODE_PATH = "/login/device/code"
TOKEN_PATH = "/login/oauth/access_token"  # noqa: S105 — URL path, not a credential
USER_PATH = "/user"
REPO_PATH_TEMPLATE = "/repos/{owner}/{repo}"
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


# Cap exception/log payloads at this many characters of body text.
# Anything longer than ~200 chars is almost certainly a server error
# page that adds noise without information; verbose echo also lets a
# misbehaving GitHub API surprise us by reflecting our request fields
# (e.g. refresh_token) back into our logs / DB. SR-4 in PR #145 review.
_ERROR_BODY_MAX_CHARS = 200


def _safe_error_summary(resp: httpx.Response) -> str:
    """Build a short, log-safe error summary from a non-2xx response.

    Prefers the standard OAuth error JSON shape (``{"error":"...",
    "error_description":"..."}``) and falls back to a truncated text body.
    Never returns more than ``_ERROR_BODY_MAX_CHARS`` characters.
    """
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        desc = body.get("error_description")
        if err and desc:
            summary = f"{err}: {desc}"
        elif err:
            summary = str(err)
        else:
            summary = ""
        if summary:
            return summary[:_ERROR_BODY_MAX_CHARS]
    text = (resp.text or "").strip()
    return text[:_ERROR_BODY_MAX_CHARS]


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
                f"device_code request failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
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
                    f"token poll transient: HTTP {resp.status_code} "
                    f"{_safe_error_summary(resp)}"
                )
            raise GitHubDeviceFlowError(
                f"token poll failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
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
                f"refresh failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
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
                f"GET /user failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
            )
        body = resp.json()
        try:
            return UserInfo(login=body["login"], id=int(body["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubDeviceFlowError(
                f"GET /user response missing fields: {body!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Repo push-access preflight (Q01R / B30 / ADR-0037 / IMPL-0014)
#
# A GitHub App user-to-server token carries the INTERSECTION of (App declared
# permissions) and (user repo permissions). If the App only declares
# Contents:read the token cannot push regardless of the user's real perms —
# which is exactly what B30 surfaces: executor "succeeds", produces a local
# branch, can't push, no PR appears.
#
# The fix per ADR-0037 is to (a) update the App to declare Contents:write +
# Pull requests:write on GitHub.com, and (b) preflight every executor run
# with a real GET /repos/{owner}/{repo} call so we fail fast with a useful
# error if the App was misconfigured. This module owns (b).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoPushAccess:
    """Effective push capability of an OAuth user token on a given repo.

    Populated from ``GET /repos/{owner}/{repo}``. The ``permissions.push``
    field on that response reflects the *authenticated principal's*
    effective perms for the repo — which for a user-to-server token is the
    intersection of (App declared perms) and (user repo perms). That's
    precisely the signal B30 needs.
    """

    can_push: bool
    reason: str = ""


async def check_repo_push_access(
    *,
    token: str,
    owner: str,
    repo: str,
    api_base_url: str = "https://api.github.com",
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> RepoPushAccess:
    """Verify that ``token`` can push to ``owner/repo`` before triggering work.

    On a definitive negative (404 / 401 / 403 / 200 with ``push=false``)
    we return ``can_push=False`` with a UI-safe reason pointing at the
    actual remediation. On a *transient* failure (network error, 429,
    5xx) we ``can_push=True`` with a reason annotating that the check
    was skipped — the executor will run and surface GitHub's real error
    if the push genuinely can't proceed. Rationale: a flaky preflight
    must never become a hard gate; that's worse than no preflight.
    """
    url = f"{api_base_url.rstrip('/')}{REPO_PATH_TEMPLATE.format(owner=owner, repo=repo)}"
    kwargs: dict = {"timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    async with httpx.AsyncClient(**kwargs) as client:
        try:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            # Network / timeout / DNS — fail OPEN. The executor will hit
            # GitHub itself; if push is truly broken it'll surface there.
            return RepoPushAccess(
                can_push=True,
                reason=(
                    f"Skipped push preflight: could not reach GitHub "
                    f"({exc.__class__.__name__})."
                ),
            )

    # Transient HTTP failures (rate limit, server error) — also fail OPEN.
    # GitHub returns 429 with rate-limit headers; treating that as "no
    # push access" would silently block every executor run during a
    # spike. The executor will retry GitHub itself and either succeed or
    # surface a real 4xx.
    if resp.status_code == 429 or 500 <= resp.status_code < 600:
        return RepoPushAccess(
            can_push=True,
            reason=(
                f"Skipped push preflight: GitHub returned HTTP "
                f"{resp.status_code} (transient)."
            ),
        )

    if resp.status_code == 404:
        return RepoPushAccess(
            can_push=False,
            reason=(
                f"Repo {owner}/{repo} is not visible to this GitHub token. "
                "The Cliff GitHub App may not be installed on this "
                "organization, or the installation was removed."
            ),
        )
    if resp.status_code == 401:
        return RepoPushAccess(
            can_push=False,
            reason=(
                "GitHub rejected the auth token (HTTP 401). The token has "
                "likely expired or been revoked — reconnect GitHub from "
                "Settings → Integrations."
            ),
        )
    if resp.status_code == 403:
        return RepoPushAccess(
            can_push=False,
            reason=(
                "GitHub denied access to this repo (HTTP 403). Check that "
                "the Cliff GitHub App is installed on this org/repo and "
                "declares Contents:write + Pull requests:write permissions."
            ),
        )
    if resp.status_code != 200:
        return RepoPushAccess(
            can_push=False,
            reason=(
                f"Unexpected response from GitHub when checking push "
                f"access (HTTP {resp.status_code})."
            ),
        )

    try:
        body = resp.json()
    except ValueError:
        return RepoPushAccess(
            can_push=False,
            reason="GitHub returned an unparseable response for the repo.",
        )

    perms = body.get("permissions") if isinstance(body, dict) else None
    if not isinstance(perms, dict):
        return RepoPushAccess(
            can_push=False,
            reason=(
                "GitHub did not return a permissions block for this repo. "
                "Update the Cliff GitHub App to declare Contents:write "
                "and Pull requests:write."
            ),
        )

    can_push = bool(perms.get("push"))
    if can_push:
        return RepoPushAccess(can_push=True, reason="")
    return RepoPushAccess(
        can_push=False,
        reason=(
            f"GitHub reports this token has no push permission on "
            f"{owner}/{repo}. The Cliff GitHub App likely declares "
            "Contents:read only — update it to Contents:write + "
            "Pull requests:write so the device-flow token can create a PR."
        ),
    )
