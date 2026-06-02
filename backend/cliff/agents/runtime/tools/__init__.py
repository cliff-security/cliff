"""In-process tool primitives for the Pydantic AI remediation_executor
(ADR-0047 / IMPL-0022).

The five tools the remediation_executor can call: ``bash``, ``edit``,
``read``, ``webfetch``, ``gh``. Each is a plain async callable taking a
``RunContext[WorkspaceDeps]`` as its first argument;
:mod:`cliff.agents.runtime.remediation_executor` registers them on the
agent. The permission tiering — auto / ask / deny — lives in
:mod:`cliff.agents.runtime.tools.permissions`.
"""

from __future__ import annotations

from cliff.agents.runtime.tools.bash import bash
from cliff.agents.runtime.tools.edit import edit
from cliff.agents.runtime.tools.gh import gh
from cliff.agents.runtime.tools.permissions import (
    classify_tool_request,
    gate_tool_call,
)
from cliff.agents.runtime.tools.read import read
from cliff.agents.runtime.tools.webfetch import webfetch

# The five tool callables the remediation_executor registers, in the
# order the system prompt references them.
EXECUTOR_TOOLS = (bash, edit, read, webfetch, gh)

__all__ = [
    "EXECUTOR_TOOLS",
    "bash",
    "classify_tool_request",
    "edit",
    "gate_tool_call",
    "gh",
    "read",
    "webfetch",
]
