"""Permission tiering for the remediation_executor's tool calls.

The classifier (``classify_tool_request`` + the two denylists +
``_is_pipe_to_shell``) is ported **verbatim** from the OpenCode-era
``cliff.agents.executor`` module — same patterns, same tier outputs — so
the migration changes the *substrate*, not the safety policy. The
OpenCode copy in ``executor.py`` is deleted in PR2.E once nothing reads
it; until then the two are identical and both are covered by tests.

``gate_tool_call`` is the new thin layer that translates a tier into
Pydantic AI's human-in-the-loop vocabulary:

* ``deny`` → raise :class:`ValueError`. The model gets a deterministic
  error string and pivots, exactly as it did when OpenCode rejected the
  command.
* ``ask`` → raise :class:`pydantic_ai.exceptions.ApprovalRequired` when
  the call has not yet been approved. Pydantic AI converts that into a
  ``DeferredToolRequests`` output (the agent declares it in its
  ``output_type`` union) so the run pauses and the executor persists the
  marker. On resume, ``ctx.tool_call_approved`` is ``True`` and the gate
  falls through to execute.
* ``auto`` → return; the tool runs immediately.

This is a *denylist* — defense-in-depth against a confused agent, NOT a
security boundary against a malicious one (that needs process sandboxing,
a separate ADR). The remediation_executor's normal workflow (git
clone/checkout/add/commit/push, gh pr create, build/test runners)
matches none of these patterns and stays on the ``auto`` path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.exceptions import ApprovalRequired

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from pydantic_ai import RunContext

    from cliff.agents.runtime.deps import WorkspaceDeps


# Never legitimate — hard-deny, don't even ask.
_CATASTROPHIC_BASH: tuple[str, ...] = (
    ":(){",          # fork bomb
    "mkfs",
    " dd ",
    "sudo ",
    "> /etc",
    ">/etc",
    "> /usr",
    ">/usr",
    "> /bin",
    ">/bin",
    "/etc/shadow",
    "/etc/passwd",
)

# Destructive or workspace-escaping, but conceivably part of a real fix —
# escalate to the user rather than hard-deny. (Per CEO: "removing a file
# requires asking for permission.")
_GATED_BASH: tuple[str, ...] = (
    "rm -",          # rm -rf, rm -f, …
    "rmdir",
    "git reset --hard",
    "git clean",
    "git push --force",
    "git push -f",
    "chmod ",
    "chown ",
    "cd /",
    "cd ~",
    "$home",
    "~/.ssh",
    "~/.aws",
    "~/.config",
)


def _is_pipe_to_shell(cmd: str) -> bool:
    """``curl …`` / ``wget …`` are fine on their own; piped into a shell
    they're remote code execution. Only the piped shape is dangerous."""
    fetches = ("curl ", "wget ")
    shells = ("| sh", "|sh", "| bash", "|bash", "|sh ", "| sh ")
    return any(f in cmd for f in fetches) and any(s in cmd for s in shells)


def classify_tool_request(tool: str, patterns: list[str]) -> str:
    """Return ``"auto"``, ``"ask"``, or ``"deny"`` for an executor tool call.

    Ported verbatim from ``executor._classify_tool_request``.

    - ``bash`` — ``deny`` for catastrophic commands, ``ask`` for
      destructive-but-conceivable ones (rm, git reset --hard, …),
      ``auto`` for everything else.
    - ``edit`` — ``ask`` if the target path is absolute or climbs out of
      the workspace via ``..``; otherwise ``auto``.
    - ``external_directory`` — ``ask``. The literal "the agent tried to
      leave the directory" signal.
    - anything else / unparseable — ``ask`` (safe default).
    """
    if tool == "external_directory":
        return "ask"

    if tool == "bash":
        cmd = " ".join(patterns).lower() if patterns else ""
        if not cmd:
            return "ask"  # can't inspect it → don't blanket-approve
        if _is_pipe_to_shell(cmd):
            return "deny"
        if any(bad in cmd for bad in _CATASTROPHIC_BASH):
            return "deny"
        if any(bad in cmd for bad in _GATED_BASH):
            return "ask"
        return "auto"

    if tool == "edit":
        for path in patterns:
            p = path.strip()
            if p.startswith("/") or p.startswith("~") or "../" in p:
                return "ask"
        return "auto"

    # mcp, unknown tools
    return "ask"


def _deny_message(tool: str, patterns: Sequence[str]) -> str:
    rendered = " ".join(patterns).strip() or "(empty)"
    return (
        f"Denied by Cliff safety policy: {tool} call {rendered!r} matches a "
        "never-permitted pattern (e.g. sudo, mkfs, dd, fork bomb, or a "
        "curl|sh pipe). This is not approvable — choose a different approach."
    )


def gate_tool_call(
    ctx: RunContext[WorkspaceDeps],
    *,
    tool: str,
    patterns: list[str],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Classify *tool*/*patterns* and enforce the tier via PA's HITL API.

    Returns the resolved tier (``"auto"`` or, on an approved re-run,
    ``"ask"``) when execution should proceed. Raises ``ValueError`` for
    ``deny`` and ``ApprovalRequired`` for an unapproved ``ask``.
    """
    tier = classify_tool_request(tool, patterns)
    if tier == "deny":
        # Unconditional — a catastrophic command is denied even if some
        # caller somehow flags it approved.
        raise ValueError(_deny_message(tool, patterns))
    if tier == "ask" and not ctx.tool_call_approved:
        raise ApprovalRequired(
            metadata=metadata or {"tool": tool, "patterns": list(patterns)}
        )
    return tier


__all__ = [
    "classify_tool_request",
    "gate_tool_call",
]
