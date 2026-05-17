"""Shallow git clone helper (Epic 1).

Used by :class:`cliff.assessment.engine.RepoCloner` and any future agentic
remediation code paths. The two guarantees here:

* Tokens never appear in subprocess args unsanitized — we redact stderr before
  logging on failure.
* ``GIT_TERMINAL_PROMPT=0`` prevents git from opening an interactive credential
  prompt when the token is missing or wrong; the existing parent env is merged
  rather than replaced because git needs ``PATH`` to locate ``git-remote-https``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class CloneError(RuntimeError):
    """``git clone`` returned non-zero."""


class CloneTimeoutError(RuntimeError):
    """``git clone`` exceeded the timeout budget."""


TOKEN_HOST_ALLOWLIST = frozenset({"github.com", "www.github.com"})

_TOKEN_URL_PATTERN = re.compile(r"x-access-token:[^@\s]+@")


def validate_repo_url(repo_url: str, *, has_token: bool = False) -> None:
    """Reject URLs we shouldn't clone from.

    * HTTPS-only — ``http://`` leaks the PAT in cleartext, ``file://`` /
      ``ssh://`` would let a user read whatever the backend process can see.
    * Hosts cannot start with ``-`` so a crafted URL cannot be interpreted as
      a git option even if ``--`` separation is somehow bypassed.
    * When a token is being injected, restrict the host to GitHub so we don't
      forward the PAT to an attacker-controlled server.
    """
    if not repo_url:
        raise ValueError("repo_url must not be empty")
    parsed = urlparse(repo_url)
    if parsed.scheme != "https":
        raise ValueError(
            f"repo_url must be https:// (got scheme {parsed.scheme!r}); "
            "non-HTTPS clones are rejected for safety"
        )
    if not parsed.netloc:
        raise ValueError(f"repo_url is missing a host: {repo_url!r}")
    host = parsed.hostname or ""
    if host.startswith("-") or parsed.netloc.startswith("-"):
        raise ValueError(f"repo_url host may not begin with '-': {repo_url!r}")
    if has_token and host.lower() not in TOKEN_HOST_ALLOWLIST:
        raise ValueError(
            f"repo_url host {host!r} is not in the token-injection allowlist; "
            "refusing to forward the GitHub token to a non-GitHub host"
        )


def inject_token(repo_url: str, token: str | None) -> str:
    """Rewrite ``https://github.com/...`` to ``https://x-access-token:TOKEN@...``."""
    if not token:
        return repo_url
    parsed = urlparse(repo_url)
    netloc = f"x-access-token:{token}@{parsed.netloc}"
    return parsed._replace(netloc=netloc).geturl()


def redact_token(text: str, token: str | None) -> str:
    """Remove the token from log-bound text in two belt-and-suspenders passes."""
    scrubbed = _TOKEN_URL_PATTERN.sub("x-access-token:***@", text)
    if token:
        scrubbed = scrubbed.replace(token, "***")
    return scrubbed


async def shallow_clone(
    repo_url: str,
    *,
    target: Path,
    token: str | None,
    timeout_s: float,
) -> None:
    """``git clone --depth 1 <url> <target>`` with timeout-driven process-group kill."""
    has_token = bool(token)
    validate_repo_url(repo_url, has_token=has_token)
    url = inject_token(repo_url, token)
    redacted_url = redact_token(url, token)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    proc = await asyncio.create_subprocess_exec(
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--",
        url,
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
    except TimeoutError:
        if proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        await proc.wait()
        raise CloneTimeoutError(
            f"git clone timed out after {timeout_s}s for {redacted_url}"
        ) from None

    if proc.returncode != 0:
        scrubbed = redact_token(stderr.decode("utf-8", errors="replace"), token)
        raise CloneError(
            f"git clone failed for {redacted_url} (exit {proc.returncode}): {scrubbed.strip()}"
        )
