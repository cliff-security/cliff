"""Real git adapters for the per-repo clone (ADR-0053 Phase 1.7).

The concrete ``sync_clone`` / ``head_sha`` the ProfileRunner is injected with in
production. Both are thin wrappers over :mod:`cliff.repos.clone`; kept separate
so the runner stays testable with fakes and these stay offline-testable against a
local repo.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

from cliff.repos.clone import clone_repo, refresh_repo

if TYPE_CHECKING:
    from pathlib import Path


async def git_head_sha(clone_dir: Path) -> str:
    """Return the checked-out HEAD sha of *clone_dir* (full 40-char)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(clone_dir),
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git rev-parse failed in {clone_dir}: {err.decode('utf-8', 'replace').strip()}"
        )
    return out.decode("utf-8").strip()


async def sync_clone(
    canonical_url: str, clone_dir: Path, token: str | None, *, timeout_s: float = 120.0
) -> None:
    """Bring *clone_dir* to the remote tip: refresh if it's a clone, else clone.

    A stale/partial directory (exists but isn't a git repo) is removed and
    re-cloned, so a half-finished previous build can't wedge the next one.
    """
    if (clone_dir / ".git").exists():
        await refresh_repo(clone_dir, token=token, timeout_s=timeout_s)
        return
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    await clone_repo(canonical_url, target=clone_dir, token=token, timeout_s=timeout_s)
