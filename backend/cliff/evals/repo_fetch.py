"""Check out a real public repo at a pinned commit for the Deep dive live lane.

The vulnerable/patched SHA-pair test (ADR-0052 §Evaluation) needs the agent to
walk *real* code, not a synthetic micro-repo. This fetches exactly one commit
(``--depth 1`` by SHA — GitHub allows reachable-SHA fetches) into a temp dir.
Public repos only (no credentials); private pairs aren't the eval's job.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class CheckoutError(RuntimeError):
    """A git step failed while checking out a pinned commit."""


async def _git(*args: str, cwd: Path, timeout: float) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise CheckoutError(f"git {args[0]} timed out after {timeout}s") from None
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise CheckoutError(f"git {args[0]} failed ({proc.returncode}): {msg}")


async def checkout_at_sha(
    repo_url: str, sha: str, target: Path, *, timeout: float = 180.0
) -> None:
    """Materialize *repo_url* at *sha* under *target* (single-commit, no history)."""
    target.mkdir(parents=True, exist_ok=True)
    await _git("init", "-q", cwd=target, timeout=timeout)
    await _git("remote", "add", "origin", repo_url, cwd=target, timeout=timeout)
    await _git("fetch", "--depth", "1", "origin", sha, cwd=target, timeout=timeout)
    await _git("checkout", "-q", "FETCH_HEAD", cwd=target, timeout=timeout)


__all__ = ["CheckoutError", "checkout_at_sha"]
