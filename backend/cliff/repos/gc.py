"""GC for the per-repo store's cached clones (ADR-0053 §4).

The app has no disk-retention machinery. A long-lived clone per repo would grow
unbounded, so this evicts the *clones* (the big, re-clonable part) least-recently-
used until the total clone footprint is back under budget. The small JSON
profile artifacts — the actual value — are kept; only ``<id>/repo/`` is removed,
so an evicted repo just re-clones on its next profile build.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def gc_repo_clones(base_dir: Path, *, max_total_bytes: int) -> list[str]:
    """Evict cached clones LRU until total clone size is within budget.

    Returns the list of repo ids whose clone was removed (most-stale first).
    Profile artifacts are never touched.
    """
    if not base_dir.exists():
        return []

    clones: list[tuple[float, int, Path, str]] = []
    for repo_dir in base_dir.iterdir():
        clone = repo_dir / "repo"
        if repo_dir.is_dir() and clone.is_dir():
            clones.append(
                (clone.stat().st_mtime, _dir_size(clone), clone, repo_dir.name)
            )

    total = sum(size for _, size, _, _ in clones)
    if total <= max_total_bytes:
        return []

    # Oldest (least recently used) first.
    clones.sort(key=lambda c: c[0])
    evicted: list[str] = []
    for _mtime, size, clone, repo_id in clones:
        if total <= max_total_bytes:
            break
        shutil.rmtree(clone)
        evicted.append(repo_id)
        total -= size
    return evicted
