"""Adapter: Cliff MCP configs → Pydantic AI toolsets."""

from __future__ import annotations

from cliff.agents.runtime.tools.mcp import build_mcp_toolsets


def test_empty_returns_empty():
    assert build_mcp_toolsets(None) == []
    assert build_mcp_toolsets({}) == []


def test_local_builds_stdio_toolset():
    configs = {
        "github": {
            "type": "local",
            "enabled": True,
            "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
            "environment": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghx"},
        }
    }
    toolsets = build_mcp_toolsets(configs)
    assert len(toolsets) == 1
    ts = toolsets[0]
    assert type(ts).__name__ == "MCPServerStdio"
    assert ts.command == "npx"
    assert list(ts.args) == ["-y", "@modelcontextprotocol/server-github"]
    assert ts.env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghx"}
    assert ts.tool_prefix == "github"


def test_remote_builds_http_toolset():
    configs = {
        "sonarqube": {
            "type": "remote",
            "enabled": True,
            "url": "https://mcp.example.com/sse",
            "headers": {"Authorization": "Bearer x"},
        }
    }
    toolsets = build_mcp_toolsets(configs)
    assert len(toolsets) == 1
    assert type(toolsets[0]).__name__ == "MCPServerStreamableHTTP"
    assert toolsets[0].tool_prefix == "sonarqube"


def test_disabled_entry_skipped():
    configs = {
        "jira": {
            "type": "local",
            "enabled": False,
            "command": ["npx", "jira-mcp"],
        }
    }
    assert build_mcp_toolsets(configs) == []


def test_malformed_entry_skipped_not_fatal():
    configs = {
        "broken": {"type": "local", "enabled": True, "command": []},
        "github": {
            "type": "local",
            "enabled": True,
            "command": ["npx", "server-github"],
        },
    }
    toolsets = build_mcp_toolsets(configs)
    # The broken one is skipped; the good one survives.
    assert len(toolsets) == 1
    assert toolsets[0].tool_prefix == "github"


def test_unknown_type_skipped():
    configs = {"weird": {"type": "carrier-pigeon", "enabled": True}}
    assert build_mcp_toolsets(configs) == []
