"""GitHub PR URL verification (closes bug B16).

When an agent claims ``status="pr_created"`` with a ``pr_url``, we used to
trust the string verbatim. Repeated dogfooding surfaced the LLM occasionally
fabricating a URL — either a compare page (``/pull/new/<branch>``), an
adjacent PR number, or a plausibly-shaped URL that points nowhere. The fix
is a strict parser + a single ``GET /repos/{o}/{r}/pulls/{n}`` round-trip.

Design notes:

* **Strict URL grammar.** ``parse_pr_url`` only accepts the canonical
  ``https://github.com/<owner>/<repo>/pull/<N>`` shape — no ``/pull/new/...``,
  no ``/tree/...``, no trailing path segments. The regex owner/repo character
  class matches GitHub's documented allow-list (alnum, dash, underscore, dot).
* **Target repo may be any org.** The verifier calls the *target* repo's API
  endpoint derived from the URL the agent emitted, not the repo we cloned
  locally. The GH PAT we pass must have read access to PRs on that repo —
  otherwise the agent could never have pushed a branch there to begin with.
* **Never raise.** Callers fold the result into an on-disk status / DB row.
  Network errors, bad JSON, timeouts all collapse into ``ok=False`` with a
  ``reason`` that's safe to show the user.
* **No fallback.** We intentionally do NOT fall back to "branch pushed, open
  the PR yourself" language. If the PR doesn't exist, the run failed and the
  UI must say so, period. This is a product decision captured on B16.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# GitHub's canonical PR URL. Owner/repo charset follows GitHub naming rules:
# - alphanumerics, hyphen, underscore, and dot (for forks like ``my.org``)
# - the regex does NOT accept trailing path segments, query strings or
#   fragments on purpose — those push the agent into "close enough" territory.
_PR_URL_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"pull/"
    r"(?P<number>[1-9][0-9]*)/?$"
)

_GITHUB_API = "https://api.github.com"
_DEFAULT_TIMEOUT = 15.0


@dataclass(frozen=True)
class ParsedPRUrl:
    owner: str
    repo: str
    number: int


def parse_pr_url(url: str | None) -> ParsedPRUrl | None:
    """Return ``(owner, repo, number)`` if *url* is a canonical PR URL.

    Returns ``None`` for ``None``/empty input, compare pages
    (``.../pull/new/<branch>``), branch pages, or anything with a query
    string or fragment. Treat a ``None`` return as "no real PR URL".
    """
    if not url:
        return None
    match = _PR_URL_RE.match(url.strip())
    if match is None:
        return None
    return ParsedPRUrl(
        owner=match.group("owner"),
        repo=match.group("repo"),
        number=int(match.group("number")),
    )


@dataclass(frozen=True)
class PRVerification:
    """Outcome of ``verify_pr_url``.

    ``ok=True`` means we fetched the PR from GitHub and it exists. ``reason``
    is machine-tag (e.g. ``not_found``, ``http_403``) plus a short human
    sentence, in a single string so callers can dump it straight into a
    status row without re-formatting.
    """

    ok: bool
    reason: str
    pr_state: str | None = None  # "open" / "closed" / "merged" on success.
    html_url: str | None = None


async def verify_pr_url(
    url: str | None,
    *,
    token: str | None,
    http: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> PRVerification:
    """Verify that *url* points to a real PR on GitHub.

    The returned ``PRVerification`` is always non-raising. A ``None`` or
    malformed *url* yields ``ok=False`` with ``reason="not_a_pull_url: ..."``.
    A 404 from GitHub yields ``reason="not_found: no PR at this URL"``.

    ``http`` may be supplied by tests to inject a mock transport. In
    production the function creates a short-lived client per call — PR
    verification happens once per agent run so pooling isn't worth the
    lifecycle complexity.
    """
    parsed = parse_pr_url(url)
    if parsed is None:
        return PRVerification(
            ok=False,
            reason=(
                f"not_a_pull_url: {url!r} is not a canonical "
                "https://github.com/<owner>/<repo>/pull/<n> URL"
            ),
        )

    endpoint = (
        f"{_GITHUB_API}/repos/{parsed.owner}/{parsed.repo}/pulls/{parsed.number}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = http is None
    client = http if http is not None else httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.get(endpoint, headers=headers, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("PR verification network error for %s: %s", url, exc)
            return PRVerification(
                ok=False,
                reason=f"network: {exc.__class__.__name__}: {exc}",
            )
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code == 200:
        try:
            data = response.json()
        except ValueError:
            return PRVerification(ok=False, reason="http_200_but_unparseable_body")
        # A real PR response has both ``number`` and ``html_url``. We double-
        # check the echoed number because GitHub can redirect to a different
        # PR if the repo was renamed — the agent's URL might have been stale.
        if (
            isinstance(data, dict)
            and data.get("number") == parsed.number
            and isinstance(data.get("html_url"), str)
        ):
            state = data.get("state")
            merged = bool(data.get("merged"))
            return PRVerification(
                ok=True,
                reason="verified",
                pr_state="merged" if merged else state,
                html_url=data["html_url"],
            )
        return PRVerification(
            ok=False,
            reason="http_200_but_pr_mismatch",
        )

    if response.status_code == 404:
        return PRVerification(
            ok=False,
            reason="not_found: GitHub returned 404 for this pull request",
        )
    if response.status_code in (401, 403):
        return PRVerification(
            ok=False,
            reason=(
                f"http_{response.status_code}: GitHub rejected the token "
                "(no access to this repo's pull requests)"
            ),
        )
    if response.status_code == 301:
        return PRVerification(
            ok=False,
            reason="http_301: repository moved — agent emitted a stale URL",
        )
    return PRVerification(
        ok=False,
        reason=f"http_{response.status_code}: unexpected GitHub response",
    )


__all__ = [
    "PRVerification",
    "ParsedPRUrl",
    "parse_pr_url",
    "verify_pr_url",
]
