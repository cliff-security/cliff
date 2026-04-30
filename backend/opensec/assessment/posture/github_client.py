"""Thin GitHub REST client used by the posture checks.

We intentionally do not depend on PyGithub — three endpoints and a token is
all we need. On 403/404/429 we return a sentinel `UnableToVerify`, not raise,
so a PAT without admin scope degrades rather than failing the whole
assessment (ADR-0025 risk row).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class UnableToVerify:
    reason: str


class GithubClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._http = http
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_repo_info(
        self, owner: str, repo: str
    ) -> dict[str, Any] | UnableToVerify:
        """Fetch minimal repo metadata — used by the onboarding connect step."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        try:
            response = await self._http.get(
                url, headers=self._headers(), timeout=self._timeout
            )
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
            response = await self._http.get(
                url, headers=self._headers(), timeout=self._timeout
            )
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
            response = await self._http.get(
                url, headers=self._headers(), params=params, timeout=self._timeout
            )
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
            response = await self._http.get(
                url, headers=self._headers(), params=params, timeout=self._timeout
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return UnableToVerify(reason=f"network: {exc.__class__.__name__}")

        if response.status_code == 200:
            body = response.json()
            return body if isinstance(body, list) else []
        if response.status_code in (401, 403, 404, 429):
            return UnableToVerify(reason=f"http_{response.status_code}")
        return UnableToVerify(reason=f"http_{response.status_code}")
