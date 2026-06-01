"""``edit`` tool — write a file inside the workspace.

Two layers of path safety:

1. The verbatim classifier (``gate_tool_call`` with ``tool="edit"``) —
   asks for approval when the path is absolute, ``~``-rooted, or contains
   a ``../`` segment.
2. A resolved-path containment check against ``ctx.deps.workspace_dir``,
   which catches escapes the textual check can miss (symlinks, mixed
   separators) and gates them the same way.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

# Runtime imports (not TYPE_CHECKING): PA introspects tool hints at
# registration; see the note in ``bash.py``.
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ApprovalRequired

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.permissions import gate_tool_call


def _escapes_workspace(workspace_dir: str, path: str) -> bool:
    """True if *path* resolves outside *workspace_dir*."""
    root = Path(workspace_dir).resolve()
    target = (root / path).resolve()
    return root != target and root not in target.parents


async def edit(ctx: RunContext[WorkspaceDeps], path: str, content: str) -> str:
    """Write *content* to *path* (relative to the workspace) and confirm.

    Raises ``ApprovalRequired`` when the path is absolute, climbs out of
    the workspace, or otherwise resolves outside it — until the user
    approves the write.
    """
    gate_tool_call(
        ctx,
        tool="edit",
        patterns=[path],
        metadata={"tool": "edit", "patterns": [path], "path": path},
    )

    # Resolved-path containment — a second line of defense the textual
    # classifier can't fully cover (symlinks, normalized separators).
    if not ctx.tool_call_approved and _escapes_workspace(
        ctx.deps.workspace_dir, path
    ):
        raise ApprovalRequired(
            metadata={
                "tool": "edit",
                "patterns": [path],
                "path": path,
                "reason": "escapes_workspace",
            }
        )

    target = (Path(ctx.deps.workspace_dir) / path).resolve()

    def _write() -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.write_text(content)

    written = await asyncio.to_thread(_write)
    rel = target.relative_to(Path(ctx.deps.workspace_dir).resolve())
    return f"Wrote {written} byte(s) to {rel}."


__all__ = ["edit"]
