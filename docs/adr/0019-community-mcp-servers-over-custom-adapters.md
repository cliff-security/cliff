# ADR-0019: Community MCP Servers Over Custom Adapters

**Date:** 2026-03-31
**Status:** Accepted
**Supersedes:** Portions of ADR-0006 (planned "first real integrations" approach)

## Context

ADR-0006 established a mock-first adapter strategy and envisioned that "real adapters implement the same interface and are added incrementally after the workflow is proven." The implicit assumption was that Cliff would build custom Python adapter classes for each external system — Wiz, Jira, GitHub, Snyk, etc.

The MCP ecosystem has matured significantly since that decision. Production-grade MCP servers now exist for many of the systems Cliff needs to integrate with:

- **GitHub:** Official `github/github-mcp-server` — 27K+ stars, MIT license, 51 tools (read_file, search_code, code_scanning_alerts, dependabot_alerts, create_issue, create_pull_request). Maintained by GitHub. Has `--read-only` mode for capability minimization.
- **Jira/Confluence:** Official `atlassian/atlassian-mcp-server` — 25 tools including `transition_issue` for workflow state changes, full CRUD, JQL search. Maintained by Atlassian. OAuth 2.1 for Cloud, with `cosmix/jira-mcp` (MIT, API token auth) as a lighter fallback for Jira Server/Data Center.
- **Wiz:** Official MCP server exists but is **cloud-only and proprietary** — not self-hostable. Not usable for Cliff's self-hosted model.

Building custom adapters for GitHub and Jira would duplicate thousands of lines of well-maintained, battle-tested code for no benefit.

## Decision

Use existing community and official MCP servers wherever they are open-source and self-hostable. Only build thin MCP wrappers for vendors that lack a suitable server.

Concretely for the first three integrations:

1. **GitHub → Zero custom code.** Use `github/github-mcp-server` via `npx -y @modelcontextprotocol/server-github`. Registry entry with credential schema (`GITHUB_PERSONAL_ACCESS_TOKEN`). Enable `--read-only` by default.

2. **Jira → Zero custom code.** Use `atlassian/atlassian-mcp-server` for Jira Cloud (OAuth 2.1). Use `cosmix/jira-mcp` as fallback for Jira Server/Data Center (API token auth). Registry entries for both variants.

3. **Wiz → Thin wrapper.** Build `cliff-mcp-wiz` — a lightweight Python MCP server that translates the Wiz REST API into 5 MCP tools: `wiz_list_findings`, `wiz_get_finding`, `wiz_get_asset_context`, `wiz_update_finding_status`, `wiz_check_finding_status`. No business logic, just API translation. Ships inline in `backend/cliff/integrations/wrappers/wiz/`.

**Decision framework for future integrations:** Before building any custom adapter, check if an open-source MCP server exists. If yes, use it. If no, build a thin wrapper. Never build a full adapter when an MCP server exists.

## Consequences

- **Easier:** Phase I-2 (first integrations) becomes primarily configuration work, not implementation. GitHub and Jira ship with registry entries and integration tests — no adapter code to write, review, or maintain.
- **Easier:** Upstream improvements to official MCP servers (new tools, bug fixes, security patches) benefit Cliff automatically via version bumps.
- **Easier:** The integration contributor experience is simpler: "find an MCP server, write a registry entry, done." Most community contributions will be registry entries, not code.
- **Easier:** Total lines of custom adapter code drops dramatically. For the first three integrations, only Wiz needs custom code (~200-300 lines for 5 tool handlers).
- **Harder:** Dependency on upstream MCP server stability. If `github/github-mcp-server` ships a breaking change, it affects Cliff. Mitigated by pinning versions in registry entries.
- **Harder:** Some MCP servers may not expose exactly the tools Cliff agents need. We accept the tools available and adapt agent prompts accordingly, rather than forking the server.
- **Harder:** Different MCP servers have different auth requirements, transport mechanisms, and quirks. The registry must capture this complexity per-integration.
- **Harder:** npm dependency for GitHub and Jira MCP servers (they're Node.js packages). Docker image must include Node.js runtime. Already satisfied by our multi-stage Dockerfile (ADR-0005, Phase 9a).
