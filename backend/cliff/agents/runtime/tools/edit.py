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
from cliff.agents.runtime.tools.permissions import escapes_workspace, gate_tool_call


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
    if not ctx.tool_call_approved and escapes_workspace(
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
    # An approved escaping write resolves outside the workspace, so
    # ``relative_to`` would raise — fall back to the absolute path for the
    # confirmation message rather than crashing after a successful write.
    root = Path(ctx.deps.workspace_dir).resolve()
    try:
        shown = target.relative_to(root)
    except ValueError:
        shown = target
    return f"Wrote {written} byte(s) to {shown}."


__all__ = ["edit"]
