# ADR-0015: MCP-Native Integration Architecture

**Date:** 2026-03-31
**Status:** Accepted

## Context

Cliff connects to external systems across four categories: finding sources (Wiz, Snyk, Tenable), ownership/context sources (CMDB, cloud tags, GitHub), ticketing systems (Jira, ServiceNow), and validation sources (re-scanners, test runners). ADR-0006 established that MVP ships with mock providers. Now we need to decide the real integration architecture.

The Model Context Protocol (MCP) is an open standard by Anthropic (donated to the Linux Foundation's Agentic AI Foundation in 2025) that solves the N×M data integration problem. MCP servers expose tools, resources, and prompts via JSON-RPC 2.0, with stdio and HTTP/SSE transports. The ecosystem already includes hundreds of production-grade MCP servers — GitHub's official server has 27K+ stars, Atlassian's covers Jira and Confluence with 25 tools.

OpenCode (our AI engine, ADR-0001) natively supports MCP servers via the `mcp` key in `opencode.json`. Since each workspace already runs its own OpenCode process in its own directory (ADR-0014), we can configure different MCP servers per workspace by generating workspace-specific `opencode.json` files.

The alternative approaches considered were:

1. **Custom Python adapter classes** — Each integration is a Python module implementing our adapter interfaces directly. Simple but creates an N×M problem: every new vendor needs a full adapter, and agents can't use the tools natively.
2. **Webhook/REST only** — Inbound webhooks and outbound REST calls managed by FastAPI. No AI-native tool invocation. Agents would need custom code to call each vendor.
3. **MCP-native** — Every external connection is either an existing MCP server or wrapped in one. Agents call MCP tools directly. OpenCode handles the protocol. The ecosystem provides most servers.

## Decision

Adopt MCP as the universal integration protocol. Every external system connection in Cliff is either an existing MCP server from the ecosystem or wrapped in a thin MCP server.

Key design choices:

1. **Three tiers of integrations:**
   - **Tier 1 — Community MCP servers (managed).** Use existing, battle-tested MCP servers (GitHub official, Atlassian official, etc.). Cliff manages their lifecycle — the user provides credentials, we spawn and manage the process. Zero custom adapter code.
   - **Tier 2 — Thin Cliff wrappers.** For vendors without open-source self-hostable MCP servers (e.g., Wiz's MCP is cloud-only), build lightweight Python MCP servers that translate the vendor REST API into MCP tools. Minimal code, no business logic.
   - **Tier 3 — User MCP servers.** Users can connect any MCP server they want. Full power, their responsibility, subject to allowlist/denylist governance.

2. **Per-workspace MCP configuration:** Each workspace's `opencode.json` includes only the MCP servers relevant to its finding. A Wiz finding gets the Wiz MCP server; a Snyk finding gets Snyk. All get ticketing and code context servers.

3. **Credential injection at config generation time:** The MCP Gateway resolves encrypted credentials from the Vault and writes them into the workspace `opencode.json` before starting the OpenCode process. The LLM never sees raw credentials.

4. **Capability minimization:** Integrations start read-only by default. Write capabilities require explicit user opt-in. Toolset scoping allows enabling specific tool subsets per integration.

5. **Inline packaging:** Thin wrappers ship inline with the Cliff codebase in `backend/cliff/integrations/wrappers/`. No separate PyPI packages. Simplicity over modularity.

## Consequences

- **Easier:** Most integrations require zero custom code — just a registry entry pointing to an existing MCP server. Phase I-2 (first integrations) ships GitHub and Jira with only configuration, not implementation.
- **Easier:** Community extensibility is built-in. Anyone who can write an MCP server can extend Cliff.
- **Easier:** Agents interact with external tools natively through OpenCode's MCP support. No translation layer between "what the integration provides" and "what the agent needs."
- **Easier:** Per-workspace isolation (ADR-0014) maps cleanly to per-workspace MCP configuration.
- **Harder:** Dependency on the MCP ecosystem's stability. If an upstream MCP server breaks, it affects Cliff workspaces.
- **Harder:** OpenCode's MCP limitations must be designed around: no runtime reconfiguration (config is static per workspace lifetime), no auto-reconnection for idle remote servers, and MCP server crashes can hang the workspace process.
- **Harder:** Credentials appear in workspace `opencode.json` as resolved values (OpenCode doesn't support vault integration). Mitigated by: ephemeral workspace directories, file permission restrictions, and regeneration on every process start.
