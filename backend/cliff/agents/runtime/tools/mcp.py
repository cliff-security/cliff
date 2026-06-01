"""Adapt Cliff's resolved MCP configs to Pydantic AI toolsets.

Cliff stores MCP server configs in OpenCode's format (the shape that
lands in a workspace's ``opencode.json``): ``{type, command, environment}``
for a local stdio server, ``{type, url, headers}`` for a remote one. The
integration gateway (:class:`cliff.integrations.gateway.MCPConfigResolver`)
resolves credential placeholders and hands the executor a
``dict[str, dict]`` keyed by integration id.

Pydantic AI is itself an MCP client: ``MCPServerStdio`` / ``MCPServerStreamableHTTP``
are toolsets you pass to ``Agent(..., toolsets=[...])``. This module is the
one-way adapter between the two — ADR-0015's MCP servers are unchanged;
only the client moves from OpenCode to PA.

PR #3 finalizes the ``opencode.json`` → Cliff-native config rename; until
then this reads the existing OpenCode-shaped dict.

On ``MCPServerStdio`` / ``MCPServerStreamableHTTP``: Pydantic AI 1.98
marks these deprecated in favour of ``MCPToolset``, but ``MCPToolset``'s
arbitrary-command form needs ``fastmcp.client.transports.StdioTransport``
— and ``fastmcp`` is not a dependency on the pinned 1.98 line. Our
configs are ``npx …`` commands (arbitrary), so the deprecated classes are
the only ones that express them without pulling in ``fastmcp``. Revisit
when the pin moves to PA v2 (tracked alongside the PR #3 config rename).
"""

from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai.toolsets import AbstractToolset

logger = logging.getLogger(__name__)


@contextmanager
def _suppress_mcp_v2_deprecation() -> Iterator[None]:
    """Silence the PA-1.98 ``MCPServerStdio``/``MCPServerStreamableHTTP``
    deprecation at the construction site — see the module docstring for
    why these classes are the right choice on the pinned line."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        yield


def build_mcp_toolsets(
    mcp_configs: dict[str, dict[str, Any]] | None,
) -> list[AbstractToolset[Any]]:
    """Convert resolved Cliff MCP configs into Pydantic AI toolsets.

    Each entry is prefixed with its integration id so tool names from
    different servers can't collide. A malformed entry is skipped with a
    warning rather than failing the whole run — one broken integration
    shouldn't block a remediation.
    """
    if not mcp_configs:
        return []

    toolsets: list[AbstractToolset[Any]] = []
    for entry_id, cfg in mcp_configs.items():
        if cfg.get("enabled") is False:
            continue
        try:
            toolset = _build_one(entry_id, cfg)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "Skipping MCP server %s: malformed config (%s)", entry_id, exc
            )
            continue
        if toolset is not None:
            toolsets.append(toolset)
    return toolsets


def _build_one(entry_id: str, cfg: dict[str, Any]) -> AbstractToolset[Any] | None:
    server_type = cfg.get("type", "local")

    if server_type == "local":
        command = cfg["command"]
        if not isinstance(command, (list, tuple)):
            raise TypeError(
                f"local MCP config 'command' must be a list, got "
                f"{type(command).__name__}"
            )
        if not command:
            raise ValueError("local MCP config has empty command")
        with _suppress_mcp_v2_deprecation():
            return MCPServerStdio(
                command=command[0],
                args=list(command[1:]),
                env=cfg.get("environment") or None,
                tool_prefix=entry_id,
            )

    if server_type == "remote":
        url = cfg["url"]
        with _suppress_mcp_v2_deprecation():
            return MCPServerStreamableHTTP(
                url=url,
                headers=cfg.get("headers") or None,
                tool_prefix=entry_id,
            )

    logger.warning(
        "Skipping MCP server %s: unknown type %r", entry_id, server_type
    )
    return None


__all__ = ["build_mcp_toolsets"]
