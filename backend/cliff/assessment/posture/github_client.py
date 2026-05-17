"""Thin GitHub REST client used by the posture checks.

We intentionally do not depend on PyGithub — three endpoints and a token is
all we need. On 403/404/429 we return a sentinel `UnableToVerify`, not raise,
so a PAT without admin scope degrades rather than failing the whole
assessment (ADR-0025 risk row).

Token refresh hook (IMPL-0010): when a ``refresh_callback`` is supplied,
a 401 response triggers exactly one refresh-and-retry. The callback is
expected to return a fresh access token (or ``None`` when refresh is
impossible). Used by GitHub App user access tokens so a workspace doesn't
fail simply because the token rotated since it was minted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class UnableToVerify:
    reason: str


def _parse_next_link(link_header: str | None) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub Link header, if any.

    GitHub paginates ``GET /user/repos`` via a ``Link`` header containing
    comma-separated ``<url>; rel="kind"`` entries. We don't need a full
    RFC 5988 parser — only the next-page URL.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = [s.strip() for s in part.split(";")]
        if len(segments) < 2 or not segments[0].startswith("<") or not segments[0].endswith(">"):
            continue
        rels = [s for s in segments[1:] if s == 'rel="next"']
        if rels:
            return segments[0][1:-1]
    return None


class GithubClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        token: str | None = None,
        timeout: float = 10.0,
        refresh_callback: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._http = http
        self._token = token
        self._timeout = timeout
        self._refresh_callback = refresh_callback

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> httpx.Response:
        """Wrapper around ``self._http.get`` with one-shot 401 refresh retry.

        Behavior:
        - When no ``refresh_callback`` is set, behaves exactly like the
          underlying ``self._http.get(...)`` (single attempt).
        - On a 401 response with a callback set, awaits the callback,
          updates ``self._token`` if a fresh token comes back, and retries
          the call exactly once. If the callback returns ``None`` or the
          retry also returns 401, the 401 response is surfaced as-is — the
          caller (existing methods) will map it to ``UnableToVerify``.
        """
        kwargs: dict[str, Any] = {
            "headers": self._headers(),
            "timeout": self._timeout,
        }
        if params is not None:
            kwargs["params"] = params

        response = await self._http.get(url, **kwargs)
        if response.status_code != 401 or self._refresh_callback is None:
            return response

        new_token = await self._refresh_callback()
        if not new_token:
            return response
        self._token = new_token
        kwargs["headers"] = self._headers()
        return await self._http.get(url, **kwargs)

    async def get_repo_info(
        self, owner: str, repo: str
    ) -> dict[str, Any] | UnableToVerify:
        """Fetch minimal repo metadata — used by the onboarding connect step."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        try:
            response = await self._get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, dict) else UnableToVerify(
                reason="unexpected_body"
            )
        return UnableToVerify(reason=f"http_{response.status_code}")

    async def get_branch_protection(
        self, owner: str, repo: str, branch: str
    ) -> dict[str, Any] | UnableToVerify | None:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/branches/{branch}/protection"
        try:
            response = await self._get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, dict) else None
        if response.status_code == 404:
            return None  # No protection rule configured.
        if response.status_code in (401, 403, 429):
            return UnableToVerify(reason=f"http_{response.status_code}")
        return UnableToVerify(reason=f"http_{response.status_code}")

    async def list_collaborators(
        self, owner: str, repo: str
    ) -> list[dict[str, Any]] | UnableToVerify:
        """``GET /repos/{owner}/{repo}/collaborators``.

        Returns the User objects with ``permissions`` and ``role_name``.
        Note: GitHub does NOT include ``last_active`` on these objects —
        :func:`check_stale_collaborators` derives activity from
        :meth:`get_user_last_event` instead.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators"
        params = {"affiliation": "direct", "per_page": "100"}
        try:
            response = await self._get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            body = response.json()
            return body if isinstance(body, list) else []
        if response.status_code in (401, 403, 404, 429):
            return UnableToVerify(reason=f"http_{response.status_code}")
        return UnableToVerify(reason=f"http_{response.status_code}")

    async def list_user_repos(
        self, *, max_pages: int = 5, per_page: int = 100
    ) -> list[dict[str, Any]] | UnableToVerify:
        """``GET /user/repos`` paginated — used by onboarding's repo picker.

        Returns the raw repo objects across up to ``max_pages`` pages
        (default 500 repos). For users with more we expose a manual-URL
        fallback in the SPA — listing every repo for accounts with thousands
        is wasteful and slows the picker. Auth/scope failures degrade to
        ``UnableToVerify`` so the route can map them to a 422 the SPA can
        surface — same pattern as :meth:`get_repo_info`.
        """
        url: str | None = (
            f"{GITHUB_API}/user/repos"
            f"?per_page={per_page}&affiliation=owner,collaborator,organization_member"
            f"&sort=updated"
        )
        repos: list[dict[str, Any]] = []
        for _ in range(max_pages):
            if url is None:
                break
            try:
                response = await self._get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

            if response.status_code != 200:
                if response.status_code in (401, 403, 404, 429):
                    return UnableToVerify(reason=f"http_{response.status_code}")
                return UnableToVerify(reason=f"http_{response.status_code}")

            body = response.json()
            if not isinstance(body, list):
                return UnableToVerify(reason="unexpected_body")
            repos.extend(item for item in body if isinstance(item, dict))

            # Follow the ``Link: <next-url>; rel="next"`` header. GitHub
            # returns no rel=next on the final page; we stop there even if
            # we haven't hit ``max_pages``.
            url = _parse_next_link(response.headers.get("Link"))

        return repos

    async def get_user_last_event(self, login: str) -> str | None | UnableToVerify:
        """Return the ISO timestamp of the user's most recent **public** event,
        or ``None`` if they have no public events at all.

        GitHub's ``GET /repos/{owner}/{repo}/collaborators`` does not expose a
        last-active timestamp; this is the fallback signal for the
        ``stale_collaborators`` check. Only public events are visible to a
        token that isn't the user's own — so a collaborator who is active
        only in private repos will appear inactive here. That trade-off is
        documented in the check's docstring.
        """
        url = f"{GITHUB_API}/users/{login}/events"
        params = {"per_page": "1"}
        try:
            response = await self._get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            body = response.json()
            if isinstance(body, list) and body:
                first = body[0]
                if isinstance(first, dict):
                    created = first.get("created_at")
                    return created if isinstance(created, str) else None
            return None
        if response.status_code == 404:
            return None  # User exists but has no public events visible.
        if response.status_code in (401, 403, 429):
            return UnableToVerify(reason=f"http_{response.status_code}")
        return UnableToVerify(reason=f"http_{response.status_code}")

    async def list_recent_commits(
        self, owner: str, repo: str, branch: str, *, limit: int = 20
    ) -> list[dict[str, Any]] | UnableToVerify:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
        params = {"sha": branch, "per_page": str(limit)}
        try:
            response = await self._get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            body = response.json()
            return body if isinstance(body, list) else []
        if response.status_code in (401, 403, 404, 429):
            return UnableToVerify(reason=f"http_{response.status_code}")
        return UnableToVerify(reason=f"http_{response.status_code}")
