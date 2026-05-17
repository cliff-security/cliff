"""Connection testers for integration credential validation (Phase I-2).

Each tester makes a lightweight HTTP call to the external service to verify
that stored credentials are valid and the service is reachable.  Testers
are dispatched by registry ID via :func:`run_connection_test`.

All testers use ``httpx.AsyncClient`` with a 10-second timeout.  Credential
values are **never** included in error messages or return values.
"""

from __future__ import annotations

import base64
import logging
from typing import Protocol
from urllib.parse import urlparse

import httpx

from cliff.models import TestConnectionResult

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ConnectionTester(Protocol):
    """Interface for integration connection testers."""

    async def test(self, credentials: dict[str, str]) -> TestConnectionResult: ...


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubConnectionTester:
    """Verify a GitHub Personal Access Token by calling ``GET /user``."""

    async def test(self, credentials: dict[str, str]) -> TestConnectionResult:
        token = credentials.get("github_personal_access_token")
        if not token:
            return TestConnectionResult(
                success=False,
                message="Missing credential: github_personal_access_token",
            )

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
        except httpx.TimeoutException:
            return TestConnectionResult(
                success=False, message="Connection timed out reaching GitHub API."
            )
        except httpx.ConnectError:
            return TestConnectionResult(
                success=False, message="Could not connect to GitHub API."
            )

        if resp.status_code == 200:
            data = resp.json()
            scopes = resp.headers.get("x-oauth-scopes", "")
            return TestConnectionResult(
                success=True,
                message=f"Connected as {data.get('login', 'unknown')}.",
                details={
                    "username": data.get("login"),
                    "scopes": scopes,
                },
            )
        if resp.status_code == 401:
            return TestConnectionResult(
                success=False, message="Invalid or expired GitHub token."
            )
        if resp.status_code == 403:
            return TestConnectionResult(
                success=False,
                message="GitHub token lacks required permissions.",
            )
        return TestConnectionResult(
            success=False,
            message=f"Unexpected GitHub API response: HTTP {resp.status_code}.",
        )


# ---------------------------------------------------------------------------
# Jira Cloud
# ---------------------------------------------------------------------------


class JiraCloudConnectionTester:
    """Verify Jira Cloud credentials by calling ``GET /rest/api/3/myself``."""

    async def test(self, credentials: dict[str, str]) -> TestConnectionResult:
        url = credentials.get("jira_url")
        email = credentials.get("jira_email")
        token = credentials.get("jira_api_token")

        if not url or not email or not token:
            missing = [
                k
                for k in ("jira_url", "jira_email", "jira_api_token")
                if not credentials.get(k)
            ]
            return TestConnectionResult(
                success=False,
                message=f"Missing credential(s): {', '.join(missing)}",
            )

        # Basic auth: email:api_token base64-encoded.
        basic = base64.b64encode(f"{email}:{token}".encode()).decode()
        endpoint = f"{url.rstrip('/')}/rest/api/3/myself"

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    endpoint,
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException:
            return TestConnectionResult(
                success=False, message="Connection timed out reaching Jira."
            )
        except httpx.ConnectError:
            return TestConnectionResult(
                success=False,
                message="Could not connect to Jira instance. Check the URL.",
            )

        if resp.status_code == 200:
            data = resp.json()
            return TestConnectionResult(
                success=True,
                message=f"Connected as {data.get('displayName', 'unknown')}.",
                details={"display_name": data.get("displayName")},
            )
        if resp.status_code == 401:
            return TestConnectionResult(
                success=False, message="Invalid Jira credentials."
            )
        if resp.status_code == 404:
            return TestConnectionResult(
                success=False,
                message="Jira instance not found. Check the URL.",
            )
        return TestConnectionResult(
            success=False,
            message=f"Unexpected Jira API response: HTTP {resp.status_code}.",
        )


# ---------------------------------------------------------------------------
# Wiz
# ---------------------------------------------------------------------------


class WizConnectionTester:
    """Verify Wiz credentials via OAuth client_credentials token exchange."""

    async def test(self, credentials: dict[str, str]) -> TestConnectionResult:
        client_id = credentials.get("wiz_client_id")
        client_secret = credentials.get("wiz_client_secret")
        api_url = credentials.get("wiz_api_url")

        if not client_id or not client_secret or not api_url:
            missing = [
                k
                for k in ("wiz_client_id", "wiz_client_secret", "wiz_api_url")
                if not credentials.get(k)
            ]
            return TestConnectionResult(
                success=False,
                message=f"Missing credential(s): {', '.join(missing)}",
            )

        # Derive auth URL from API URL (e.g. api.us20.app.wiz.io → auth.app.wiz.io).
        auth_url = self._derive_auth_url(api_url)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    auth_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "audience": "wiz-api",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.TimeoutException:
            return TestConnectionResult(
                success=False, message="Connection timed out reaching Wiz auth."
            )
        except httpx.ConnectError:
            return TestConnectionResult(
                success=False,
                message="Could not connect to Wiz auth endpoint.",
            )

        if resp.status_code == 200:
            data = resp.json()
            if "access_token" in data:
                return TestConnectionResult(
                    success=True,
                    message="Wiz authentication successful.",
                    details={"token_type": data.get("token_type", "bearer")},
                )
            return TestConnectionResult(
                success=False,
                message="Wiz returned 200 but no access token. Check credentials.",
            )
        if resp.status_code in (401, 403):
            return TestConnectionResult(
                success=False, message="Invalid Wiz client credentials."
            )
        return TestConnectionResult(
            success=False,
            message=f"Unexpected Wiz auth response: HTTP {resp.status_code}.",
        )

    @staticmethod
    def _derive_auth_url(api_url: str) -> str:
        """Derive the Wiz OAuth token URL from the GraphQL API URL.

        ``https://api.us20.app.wiz.io/graphql`` → ``https://auth.app.wiz.io/oauth/token``
        """
        parsed = urlparse(api_url)
        host_parts = parsed.hostname.split(".") if parsed.hostname else []
        # Find 'app.wiz.io' suffix and prepend 'auth'.
        try:
            app_idx = host_parts.index("app")
            auth_host = "auth." + ".".join(host_parts[app_idx:])
        except (ValueError, IndexError):
            # Fallback: default Wiz auth endpoint.
            auth_host = "auth.app.wiz.io"
        return f"https://{auth_host}/oauth/token"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TESTER_REGISTRY: dict[str, ConnectionTester] = {
    "github": GitHubConnectionTester(),
    "jira-cloud": JiraCloudConnectionTester(),
    "wiz": WizConnectionTester(),
}


def get_tester(registry_id: str) -> ConnectionTester | None:
    """Look up a connection tester by integration registry ID."""
    return _TESTER_REGISTRY.get(registry_id)


async def run_connection_test(
    registry_id: str, credentials: dict[str, str]
) -> TestConnectionResult | None:
    """Run a connection test for the given integration.

    Returns ``None`` if no tester is registered for *registry_id* (caller
    should fall back to the generic "credentials decrypted" response).
    """
    tester = get_tester(registry_id)
    if tester is None:
        return None
    return await tester.test(credentials)
