# ADR-0018: MCP Gateway — Build Inline, Informed by Ecosystem

**Date:** 2026-03-31
**Status:** Accepted

## Context

Cliff needs a component that manages MCP server connections for each workspace: starting/stopping processes, injecting credentials, enforcing permissions, intercepting tool calls for audit logging, and tying the MCP server lifecycle to the workspace lifecycle (ADR-0014).

We evaluated 12+ open-source MCP Gateway projects:

| Project | Strengths | Why not a drop-in fit |
|---------|-----------|----------------------|
| **Gate22** (Apache 2.0) | Function-level permissions, per-call audit logging, tool poisoning detection | No OpenCode integration, no workspace-scoped lifecycle |
| **Lasso MCP Gateway** | Credential sanitization, PII protection, reputation scoring | Focused on sanitization, not lifecycle management |
| **MCPProxy.go** | Docker isolation, quarantine workflow, OAuth 2.1/PKCE | Go-based, doesn't integrate with our Python backend |
| **Fiberplane Gateway** | Traffic inspection, real-time logging dashboard | Observability-focused, no credential injection |
| **Microsoft MCP Gateway** | Dual-plane RBAC, session-aware routing | Heavy Azure/Kubernetes dependency |
| **MCP Mesh** (decocms) | Encrypted token vault, workspace-scoped RBAC | Sustainable Use License, not fully open |

The core problem: none of these gateways understand OpenCode's workspace process model (ADR-0014). Our gateway must generate per-workspace `opencode.json` configs, resolve credentials from the Vault (ADR-0016), manage MCP server processes alongside OpenCode processes, and tie the lifecycle to workspace idle timeouts.

## Decision

Build the MCP Gateway inline within the Cliff codebase, heavily borrowing patterns from the best existing projects.

Key design choices:

1. **Inline, not external dependency.** The gateway lives in `backend/cliff/integrations/gateway.py` — part of the Cliff monorepo. No separate package, no additional deployment artifact. This aligns with our inline packaging decision and keeps the system simple for self-hosted users.

2. **Patterns borrowed from ecosystem:**
   - **Gate22** → Per-call audit event schema and function-level permission model
   - **Lasso** → Credential sanitization patterns (masking tokens in logs, PII detection)
   - **MCPProxy.go** → Quarantine workflow for untrusted user MCP servers (new servers require explicit trust approval before first use)
   - **MCP Mesh** → Workspace-scoped credential resolution design

3. **Workspace lifecycle integration.** The gateway extends the existing `WorkspaceProcessPool` (ADR-0014, Layer 3):
   - When a workspace starts: determine required integrations from finding metadata → resolve credentials from Vault → generate workspace `opencode.json` with MCP server configs → start OpenCode process (which starts MCP child processes)
   - When a workspace goes idle: OpenCode process stops → MCP child processes terminate
   - When a workspace reopens: fresh `opencode.json` generated → new OpenCode process → new MCP servers

4. **Credential placeholder resolution.** Registry entries use `${credential:wiz.client_id}` placeholders. The gateway resolves these from the Vault at workspace creation time, writing real values into the ephemeral `opencode.json`. This is the only point where plaintext credentials exist outside the Vault.

5. **Permission enforcement.** Three action tiers:
   - **Tier 0 — Read-only.** No approval needed. Default for all integrations.
   - **Tier 1 — Contextual enrichment.** No approval needed but fully logged.
   - **Tier 2 — Mutation/write.** Requires explicit user opt-in per integration. Sensitive writes require human confirmation with full parameter visibility.

6. **Governance controls.** Following Claude Code's managed-mcp.json pattern:
   - System-level allowlist/denylist for MCP server commands and URLs
   - Trust gate for user-provided MCP servers (first-run approval required)
   - Capability minimization (toolset scoping per integration)

## Consequences

- **Easier:** Single codebase, single deployment. No additional infrastructure for the gateway.
- **Easier:** Workspace lifecycle integration is seamless because the gateway is part of the same Python process managing the workspace pool.
- **Easier:** Patterns from Gate22, Lasso, and MCPProxy.go are proven — we're adopting battle-tested designs, not inventing new ones.
- **Harder:** We own the maintenance of the gateway component. If the MCP ecosystem evolves gateway standards, we may need to adapt.
- **Harder:** The gateway must handle OpenCode's limitations: no runtime MCP reconfiguration, no auto-reconnection for idle remote servers, MCP server crashes can hang the workspace. We mitigate with health monitoring and process restart.
- **Harder:** Testing requires mocking MCP servers for unit tests and running real MCP servers for integration tests. Adds test infrastructure complexity.
