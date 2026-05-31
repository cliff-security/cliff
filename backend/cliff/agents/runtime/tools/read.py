"""``read`` tool — read a file from the workspace.

Auto-tier (no approval): reading is non-destructive. Output is capped at
50 KB so a giant lockfile or minified bundle can't blow the model's
context; larger files return a prefix plus a truncation marker.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from cliff.agents.runtime.deps import WorkspaceDeps

_MAX_READ_BYTES = 50 * 1024


async def read(ctx: RunContext[WorkspaceDeps], path: str) -> str:
    """Return the contents of *path* (relative to the workspace).

    Reads at most 50 KB; larger files are truncated with a marker so the
    agent knows the view is partial.
    """
    target = (Path(ctx.deps.workspace_dir) / path).resolve()

    def _read() -> tuple[str, bool]:
        try:
            with target.open("rb") as fh:
                raw = fh.read(_MAX_READ_BYTES + 1)
        except FileNotFoundError:
            return (f"[file not found: {path}]", False)
        except OSError as exc:
            return (f"[could not read {path}: {exc}]", False)
        truncated = len(raw) > _MAX_READ_BYTES
        text = raw[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
        return (text, truncated)

    body, truncated = await asyncio.to_thread(_read)
    if truncated:
        return body + f"\n[... truncated at {_MAX_READ_BYTES} bytes ...]"
    return body


__all__ = ["read"]
