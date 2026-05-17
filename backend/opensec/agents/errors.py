"""Agent execution error types."""

from __future__ import annotations


class AgentExecutionError(Exception):
    """Base class for agent execution errors."""


class AgentTimeoutError(AgentExecutionError):
    """Agent did not complete within the timeout budget."""


class AgentProcessError(AgentExecutionError):
    """The workspace's OpenCode process is unavailable or crashed."""


class AgentRateLimitError(AgentProcessError):
    """Upstream AI provider rate-limited the request (HTTP 429 / "too many requests").

    Subclasses ``AgentProcessError`` so any code path that already catches
    process errors keeps working; new code paths (the executor retry loop)
    catch this specifically to apply exponential backoff (EF-B17).
    """


class AgentBusyError(AgentExecutionError):
    """Another agent is already running in this workspace."""
