"""Entry point for the Wiz MCP server.

Usage:
    python -m cliff.integrations.wrappers.wiz

Environment:
    WIZ_CLIENT_ID      — Wiz service account client ID
    WIZ_CLIENT_SECRET  — Wiz service account client secret
    WIZ_API_URL        — Wiz GraphQL API endpoint (e.g. https://api.us20.app.wiz.io/graphql)
"""

from __future__ import annotations

import os
import sys

from cliff.integrations.wrappers.wiz.server import WizMCPServer


def main() -> None:
    client_id = os.environ.get("WIZ_CLIENT_ID", "")
    client_secret = os.environ.get("WIZ_CLIENT_SECRET", "")
    api_url = os.environ.get("WIZ_API_URL", "")

    if not client_id or not client_secret or not api_url:
        missing = [
            k
            for k in ("WIZ_CLIENT_ID", "WIZ_CLIENT_SECRET", "WIZ_API_URL")
            if not os.environ.get(k)
        ]
        print(f"Error: missing environment variable(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    server = WizMCPServer(client_id=client_id, client_secret=client_secret, api_url=api_url)
    server.run()


if __name__ == "__main__":
    main()
