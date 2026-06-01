"""``bash`` tool — run a shell command inside the workspace.

Replaces OpenCode's bash tool dispatch for the remediation_executor.
Classification (auto / ask / deny) happens before execution via
:func:`cliff.agents.runtime.tools.permissions.gate_tool_call`; output is
trimmed to the last 200 lines so a noisy build log can't blow the model's
context window.
"""

from __future__ import annotations

import asyncio
import subprocess

# Imported at runtime (not under TYPE_CHECKING): Pydantic AI introspects a
# tool's type hints via ``get_type_hints`` when it's registered, and with
# ``from __future__ import annotations`` the ``RunContext[WorkspaceDeps]``
# annotation is a string that must resolve against the module globals.
from pydantic_ai import RunContext

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.permissions import gate_tool_call

# Wall-clock ceiling for a single command. The agent's overall budget is
# the outer ``asyncio.wait_for`` in the executor (600 s); this keeps one
# hung command (a clone of a huge repo, an interactive prompt) from
# eating that whole budget.
_BASH_TIMEOUT_SECONDS = 180.0

# Keep the last N lines of combined stdout/stderr. Build/test runners can
# emit thousands of lines; the tail is where failures and the final state
# live.
_MAX_OUTPUT_LINES = 200


def _trim_output(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= _MAX_OUTPUT_LINES:
        return text
    dropped = len(lines) - _MAX_OUTPUT_LINES
    tail = lines[-_MAX_OUTPUT_LINES:]
    return f"[... {dropped} earlier line(s) trimmed ...]\n" + "\n".join(tail)


async def bash(ctx: RunContext[WorkspaceDeps], command: str) -> str:
    """Run *command* in the workspace and return its combined output.

    The command is classified first: catastrophic patterns (sudo, mkfs,
    curl|sh, …) raise ``ValueError``; destructive-but-conceivable ones
    (rm, git reset --hard, …) raise ``ApprovalRequired`` until the user
    approves; everything else runs immediately.
    """
    gate_tool_call(
        ctx,
        tool="bash",
        patterns=[command],
        # ``patterns`` mirrors what the frontend approval prompt renders;
        # ``command`` is the human-readable form for richer display.
        metadata={"tool": "bash", "patterns": [command], "command": command},
    )

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=True,  # noqa: S602 — the remediation agent legitimately
            # needs a shell (pipes, &&, redirects); the denylist gate above
            # is the defense-in-depth layer, not shell=False.
            cwd=ctx.deps.workspace_dir,
            capture_output=True,
            text=True,
            timeout=_BASH_TIMEOUT_SECONDS,
            env=ctx.deps.env_vars or None,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return (
            f"Command timed out after {_BASH_TIMEOUT_SECONDS:.0f}s and was "
            "killed. If this was a long build, split it into smaller steps."
        )

    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout.rstrip("\n"))
    if proc.stderr:
        parts.append(proc.stderr.rstrip("\n"))
    body = _trim_output("\n".join(p for p in parts if p))
    return f"exit_code={proc.returncode}\n{body}".rstrip("\n")


__all__ = ["bash"]
