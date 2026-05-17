"""Wiz MCP server — thin wrapper around the Wiz GraphQL API.

Implements the MCP protocol (JSON-RPC over stdio with Content-Length framing)
without importing the ``mcp`` package.  Follows the same pattern as
``tests/fixtures/mock_mcp_server.py``.

Provides 5 tools:
- wiz_list_findings      — query Wiz issues (read)
- wiz_get_finding        — get a single issue by ID (read)
- wiz_get_asset_context  — get cloud resource details (read)
- wiz_update_finding_status — update issue status (mutate, tier 2)
- wiz_check_finding_status  — check current issue status (read)
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SERVER_NAME = "cliff-mcp-wiz"
_SERVER_VERSION = "0.1.0"
_PROTOCOL_VERSION = "2024-11-05"
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Token is refreshed 5 minutes before expiry.
_TOKEN_REFRESH_MARGIN_S = 300

# ---------------------------------------------------------------------------
# Tool definitions (MCP schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "wiz_list_findings",
        "description": "List Wiz security findings (issues) with optional filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"],
                    "description": "Filter by severity level.",
                },
                "status": {
                    "type": "string",
                    "enum": ["OPEN", "IN_PROGRESS", "RESOLVED", "REJECTED"],
                    "description": "Filter by issue status.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 50).",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "wiz_get_finding",
        "description": "Get detailed information about a single Wiz finding by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {
                    "type": "string",
                    "description": "The Wiz issue ID.",
                },
            },
            "required": ["finding_id"],
        },
    },
    {
        "name": "wiz_get_asset_context",
        "description": "Get cloud resource details for an asset associated with a finding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "The Wiz graph entity (asset) ID.",
                },
            },
            "required": ["asset_id"],
        },
    },
    {
        "name": "wiz_update_finding_status",
        "description": "Update the status of a Wiz finding. Requires action tier 2 (mutation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {
                    "type": "string",
                    "description": "The Wiz issue ID.",
                },
                "status": {
                    "type": "string",
                    "enum": ["OPEN", "IN_PROGRESS", "RESOLVED", "REJECTED"],
                    "description": "New status for the finding.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional note explaining the status change.",
                },
            },
            "required": ["finding_id", "status"],
        },
    },
    {
        "name": "wiz_check_finding_status",
        "description": "Check the current status of a Wiz finding (lightweight read).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {
                    "type": "string",
                    "description": "The Wiz issue ID.",
                },
            },
            "required": ["finding_id"],
        },
    },
]

# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

_GQL_LIST_FINDINGS = """
query ListIssues($first: Int, $filterBy: IssueFilters) {
  issuesV2(first: $first, filterBy: $filterBy) {
    nodes {
      id
      sourceRule { name }
      severity
      status
      createdAt
      updatedAt
      entitySnapshot { id name type }
    }
    totalCount
  }
}
"""

_GQL_GET_FINDING = """
query GetIssue($id: ID!) {
  issue(id: $id) {
    id
    sourceRule { name description }
    severity
    status
    createdAt
    updatedAt
    notes { text createdAt }
    entitySnapshot { id name type cloudPlatform region }
    remediation
  }
}
"""

_GQL_GET_ASSET = """
query GetEntity($id: String!) {
  graphEntity(id: $id) {
    id
    name
    type
    properties
  }
}
"""

_GQL_UPDATE_STATUS = """
mutation UpdateIssue($issueId: ID!, $patch: UpdateIssuePatch!) {
  updateIssue(input: { id: $issueId, patch: $patch }) {
    issue { id status updatedAt }
  }
}
"""


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


class WizMCPServer:
    """Thin MCP server wrapping the Wiz GraphQL API."""

    def __init__(self, client_id: str, client_secret: str, api_url: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_url = api_url
        self._auth_url = self._derive_auth_url(api_url)

        # Token cache.
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # -- stdio loop --------------------------------------------------------

    def run(self) -> None:
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        while True:
            line = sys.stdin.readline()
            if not line:
                break  # EOF

            line = line.strip()
            if not line.lower().startswith("content-length:"):
                continue

            content_length = int(line.split(":")[1].strip())
            sys.stdin.readline()  # blank line
            body = sys.stdin.read(content_length)
            if not body:
                break

            try:
                request = json.loads(body)
            except json.JSONDecodeError:
                continue

            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params", {})

            if method == "initialize":
                self._respond(request_id, {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
                })
            elif method == "tools/list":
                self._respond(request_id, {"tools": TOOLS})
            elif method == "tools/call":
                self._handle_tool_call(request_id, params)
            elif method == "notifications/initialized":
                pass  # Client acknowledgement — no response needed.
            else:
                self._error(request_id, -32601, f"Unknown method: {method}")

    # -- tool dispatch -----------------------------------------------------

    def _handle_tool_call(self, request_id: int | str, params: dict) -> None:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handlers = {
            "wiz_list_findings": self._tool_list_findings,
            "wiz_get_finding": self._tool_get_finding,
            "wiz_get_asset_context": self._tool_get_asset_context,
            "wiz_update_finding_status": self._tool_update_finding_status,
            "wiz_check_finding_status": self._tool_check_finding_status,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            self._error(request_id, -32601, f"Unknown tool: {tool_name}")
            return

        try:
            result = handler(arguments)
            self._respond(request_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            })
        except WizAPIError as exc:
            self._respond(request_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                "isError": True,
            })
        except Exception as exc:
            self._error(request_id, -32000, f"Internal error: {exc}")

    # -- tool implementations ----------------------------------------------

    def _tool_list_findings(self, args: dict) -> Any:
        variables: dict[str, Any] = {"first": args.get("limit", 50)}
        filters: dict[str, Any] = {}
        if "severity" in args:
            filters["severity"] = [args["severity"]]
        if "status" in args:
            filters["status"] = [args["status"]]
        if filters:
            variables["filterBy"] = filters
        data = self._graphql(_GQL_LIST_FINDINGS, variables)
        return data.get("issuesV2", {})

    def _tool_get_finding(self, args: dict) -> Any:
        finding_id = args.get("finding_id")
        if not finding_id:
            raise WizAPIError("finding_id is required")
        data = self._graphql(_GQL_GET_FINDING, {"id": finding_id})
        return data.get("issue")

    def _tool_get_asset_context(self, args: dict) -> Any:
        asset_id = args.get("asset_id")
        if not asset_id:
            raise WizAPIError("asset_id is required")
        data = self._graphql(_GQL_GET_ASSET, {"id": asset_id})
        return data.get("graphEntity")

    def _tool_update_finding_status(self, args: dict) -> Any:
        finding_id = args.get("finding_id")
        status = args.get("status")
        if not finding_id or not status:
            raise WizAPIError("finding_id and status are required")
        patch: dict[str, Any] = {"status": status}
        if "note" in args:
            patch["note"] = args["note"]
        data = self._graphql(_GQL_UPDATE_STATUS, {"issueId": finding_id, "patch": patch})
        return data.get("updateIssue", {}).get("issue")

    def _tool_check_finding_status(self, args: dict) -> Any:
        finding_id = args.get("finding_id")
        if not finding_id:
            raise WizAPIError("finding_id is required")
        data = self._graphql(_GQL_GET_FINDING, {"id": finding_id})
        issue = data.get("issue", {})
        return {"id": issue.get("id"), "status": issue.get("status")}

    # -- GraphQL + OAuth ---------------------------------------------------

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query against the Wiz API."""
        self._ensure_token()
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(
                self._api_url,
                json={"query": query, "variables": variables or {}},
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            raise WizAPIError(f"Wiz API returned HTTP {resp.status_code}")
        data = resp.json()
        if "errors" in data:
            messages = [e.get("message", "unknown") for e in data["errors"]]
            raise WizAPIError(f"GraphQL error: {'; '.join(messages)}")
        return data.get("data", {})

    def _ensure_token(self) -> None:
        """Fetch or refresh the OAuth access token."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return

        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(
                self._auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "audience": "wiz-api",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if resp.status_code != 200:
            raise WizAPIError(f"OAuth token request failed: HTTP {resp.status_code}")

        token_data = resp.json()
        if "access_token" not in token_data:
            raise WizAPIError("OAuth response missing access_token")

        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN_S

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _derive_auth_url(api_url: str) -> str:
        """Derive the Wiz OAuth token URL from the GraphQL API URL."""
        parsed = urlparse(api_url)
        host_parts = parsed.hostname.split(".") if parsed.hostname else []
        try:
            app_idx = host_parts.index("app")
            auth_host = "auth." + ".".join(host_parts[app_idx:])
        except (ValueError, IndexError):
            auth_host = "auth.app.wiz.io"
        return f"https://{auth_host}/oauth/token"

    @staticmethod
    def _respond(request_id: int | str | None, result: dict) -> None:
        """Write a JSON-RPC success response to stdout."""
        response = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
        header = f"Content-Length: {len(response)}\r\n\r\n"
        sys.stdout.write(header + response)
        sys.stdout.flush()

    @staticmethod
    def _error(request_id: int | str | None, code: int, message: str) -> None:
        """Write a JSON-RPC error response to stdout."""
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        })
        header = f"Content-Length: {len(response)}\r\n\r\n"
        sys.stdout.write(header + response)
        sys.stdout.flush()


class WizAPIError(Exception):
    """Raised when a Wiz API call fails."""
