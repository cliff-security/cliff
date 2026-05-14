"""Reference-URL verification for agent output (Q01-B08).

The Finding Enricher emits ``references`` as free-text, and on weaker models
it fabricates *specific* identifiers — a GitHub advisory ID that 404s, a
commit URL with Cyrillic glyphs jammed into the SHA. For a security tool a
fabricated citation is worse than a missing one: an engineer pastes the GHSA
link into a ticket and it dead-ends.

``clean_references`` is the safety net. It runs two passes over the
enricher's reference list:

1. **Sanitize** (no network) — drop URLs that are structurally impossible:
   non-ASCII characters (the Cyrillic-SHA case), unparseable URLs, non-HTTP
   schemes, GitHub commit URLs whose SHA isn't 7-40 hex chars.
2. **Verify** (network, best-effort, parallel) — GET each survivor and drop
   the ones the host answers ``404``/``410`` for. Timeouts, connection
   errors, ``5xx`` and ``429`` are *kept* — we only drop on a definitive
   "does not exist", never on a flaky probe.

Never raises. A reference that cannot be positively disproven is kept.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# A GitHub commit URL's SHA segment — git object names are 7-40 hex chars.
# Anything else (Cyrillic, punctuation, wrong length) is a fabricated SHA.
_GITHUB_COMMIT_RE = re.compile(
    r"^/[^/]+/[^/]+/commit/(?P<sha>[^/]+)/?$"
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

_DEFAULT_TIMEOUT = 8.0
# Cap concurrency so a long reference list can't open dozens of sockets.
_MAX_CONCURRENCY = 8


@dataclass
class ReferenceCheck:
    """Outcome of ``clean_references``.

    ``kept`` preserves input order. ``dropped`` is ``(url, reason)`` pairs —
    ``reason`` is a short machine-ish tag safe to log.
    """

    kept: list[str] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)


def _sanitize_reason(url: str) -> str | None:
    """Return a drop reason if *url* is structurally impossible, else ``None``."""
    if not url or not url.strip():
        return "empty"
    candidate = url.strip()
    # Non-ASCII anywhere in the URL — a real citation never needs it, and it
    # is the exact shape of the fabricated commit SHA (Cyrillic glyphs).
    if not candidate.isascii():
        return "non_ascii"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return "unparseable"
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "not_http_url"
    # GitHub commit URLs carry a SHA that must be a real git object name.
    if parsed.netloc.lower() in ("github.com", "www.github.com"):
        commit = _GITHUB_COMMIT_RE.match(parsed.path)
        if commit and not _SHA_RE.match(commit.group("sha")):
            return "malformed_commit_sha"
    return None


async def _probe(
    url: str, client: httpx.AsyncClient, timeout: float
) -> str | None:
    """Return a drop reason if the host says *url* does not exist, else ``None``.

    Only a definitive ``404``/``410`` drops a reference. Every ambiguous
    outcome — redirects, auth walls, rate limits, server errors, network
    failures — keeps it: a flaky probe must never erase a real citation.
    """
    try:
        resp = await client.get(
            url, timeout=timeout, follow_redirects=True
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.debug("reference probe network error for %s: %s", url, exc)
        return None
    if resp.status_code in (404, 410):
        return f"http_{resp.status_code}"
    return None


async def clean_references(
    references: object,
    *,
    http: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> ReferenceCheck:
    """Sanitize then verify *references*; return the surviving URLs.

    *references* is taken straight from agent output, so it may be ``None``,
    a non-list, or contain non-strings — all of which collapse to an empty
    result rather than raising. ``http`` may be injected by tests.
    """
    if not isinstance(references, list):
        return ReferenceCheck()

    result = ReferenceCheck()

    # Pass 1 — sanitize (deterministic, no network). Dedupe here too so a
    # repeated URL is probed once.
    seen: set[str] = set()
    survivors: list[str] = []
    for raw in references:
        if not isinstance(raw, str):
            result.dropped.append((str(raw), "not_a_string"))
            continue
        url = raw.strip()
        if url in seen:
            continue
        seen.add(url)
        reason = _sanitize_reason(url)
        if reason is not None:
            result.dropped.append((url, reason))
        else:
            survivors.append(url)

    if not survivors:
        return result

    # Pass 2 — verify (network, best-effort, parallel).
    owns_client = http is None
    client = http if http is not None else httpx.AsyncClient(timeout=timeout)
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _guarded(u: str) -> str | None:
        async with semaphore:
            return await _probe(u, client, timeout)

    try:
        reasons = await asyncio.gather(
            *(_guarded(u) for u in survivors), return_exceptions=True
        )
    finally:
        if owns_client:
            await client.aclose()

    for url, reason in zip(survivors, reasons, strict=True):
        # An unexpected exception from the probe is treated as "could not
        # disprove" — keep the reference rather than erase it on a bug.
        if isinstance(reason, str):
            result.dropped.append((url, reason))
        else:
            result.kept.append(url)

    return result


__all__ = ["ReferenceCheck", "clean_references"]
