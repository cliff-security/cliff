"""``grep`` tool — read-only regex search over the workspace (ADR-0052 §3).

The Deep dive's code-walkers (``trace_path`` / ``challenge``) need to find
references without a shell. This is pure-Python regex search scoped to the
workspace (the cached clone), no subprocess, so it's safe (read-only, can't
escape) and deterministic (gradeable by the eval). Auto-tier, like ``read``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic_ai import RunContext

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.permissions import escapes_workspace

_MAX_MATCHES = 100
_MAX_FILE_BYTES = 1024 * 1024
_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache"}
)


def search_workspace(workspace_dir: str, pattern: str, path: str = ".") -> str:
    """Search files under *workspace_dir*/*path* for *pattern* (regex).

    Returns up to 100 ``relpath:line: text`` matches, or a bracketed status
    ([refused] / [invalid regex] / [no matches]). Pure + synchronous so it's
    unit-testable without a RunContext; the tool wraps it on a thread.
    """
    if escapes_workspace(workspace_dir, path):
        return f"[refused: {path} resolves outside the workspace]"
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"[invalid regex: {exc}]"

    # Resolve the root too: on macOS a temp dir like /var/folders/... canonicalizes
    # to /private/var/folders/..., and base.resolve() below follows that symlink —
    # so an unresolved root would break relative_to() on every match.
    root = Path(workspace_dir).resolve()
    base = (root / path).resolve()
    if not base.exists():
        return f"[path not found: {path}]"

    matches: list[str] = []
    candidates = [base] if base.is_file() else base.rglob("*")
    for f in candidates:
        if len(matches) >= _MAX_MATCHES:
            break
        if not f.is_file() or any(part in _SKIP_DIRS for part in f.parts):
            continue
        try:
            if f.stat().st_size > _MAX_FILE_BYTES:
                continue
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if rx.search(line):
                        rel = f.relative_to(root)
                        matches.append(f"{rel}:{lineno}: {line.rstrip()[:200]}")
                        if len(matches) >= _MAX_MATCHES:
                            break
        except OSError:
            continue

    if not matches:
        return f"[no matches for {pattern!r}]"
    out = "\n".join(matches)
    if len(matches) >= _MAX_MATCHES:
        out += f"\n[... capped at {_MAX_MATCHES} matches ...]"
    return out


async def grep(ctx: RunContext[WorkspaceDeps], pattern: str, path: str = ".") -> str:
    """Search the workspace for *pattern* (regex), under *path* (default: root)."""
    out = await asyncio.to_thread(
        search_workspace, ctx.deps.workspace_dir, pattern, path
    )
    budget = ctx.deps.read_budget
    if budget is not None and not budget.take(len(out.encode("utf-8", errors="ignore"))):
        return "[grep budget exhausted for this analysis]"
    return out


__all__ = ["grep", "search_workspace"]
