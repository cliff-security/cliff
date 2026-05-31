"""``webfetch`` tool — fetch a URL's text body.

Auto-tier: a GET is non-destructive. Bounded by a 30 s timeout and a
content-type allowlist (text/* and application/json) so the agent can
read an advisory or a changelog but can't pull down a binary.

SSRF note: this is an outbound GET on a model-chosen URL. The community
edition runs single-tenant on the operator's own machine, so the blast
radius is the operator's own network — the same trust level the bash
tool already grants. A hardened multi-tenant deployment needs an
egress policy here (separate ADR); that's out of scope for PR #2.
"""

from __future__ import annotations

import httpx

# Runtime imports (not TYPE_CHECKING): PA introspects tool hints at
# registration; see the note in ``bash.py``.
from pydantic_ai import RunContext

from cliff.agents.runtime.deps import WorkspaceDeps

_WEBFETCH_TIMEOUT_SECONDS = 30.0
_MAX_BODY_BYTES = 50 * 1024
_ALLOWED_CONTENT_TYPES = ("text/", "application/json")


async def webfetch(ctx: RunContext[WorkspaceDeps], url: str) -> str:
    """GET *url* and return its text body (text/* or JSON only)."""
    try:
        async with httpx.AsyncClient(
            timeout=_WEBFETCH_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return f"[fetch failed: {exc}]"

    content_type = resp.headers.get("content-type", "").lower()
    if not any(content_type.startswith(t) for t in _ALLOWED_CONTENT_TYPES):
        return (
            f"[unsupported content-type {content_type!r}; webfetch only "
            "returns text/* and application/json]"
        )

    body = resp.text
    if len(body.encode("utf-8")) > _MAX_BODY_BYTES:
        body = body.encode("utf-8")[:_MAX_BODY_BYTES].decode(
            "utf-8", errors="replace"
        )
        body += f"\n[... truncated at {_MAX_BODY_BYTES} bytes ...]"
    return f"HTTP {resp.status_code}\n{body}"


__all__ = ["webfetch"]
