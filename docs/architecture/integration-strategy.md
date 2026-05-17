# Cliff Integration Strategy & Roadmap

> **Status:** Draft v2 — March 31, 2026
> **Author:** Cliff Core Team
> **Scope:** Community Edition (self-hosted, single-user)
> **Updated:** Incorporates MCP Gateway landscape analysis, OpenCode MCP mechanics, two-plane architecture, and enterprise governance patterns

---

## 1. Why integrations are everything

Cliff's value proposition is simple: one chat interface to remediate vulnerabilities across your entire security stack. Without integrations, it's a chatbot. With integrations, it's the operational center of gravity for cybersecurity work.

The insight driving this strategy comes from how developer tools like Claude Code and OpenCode solved the same problem for engineering. Claude Code doesn't replace your IDE, Git, or CI — it connects to all of them through MCP servers and lets you orchestrate everything from a single conversation. Cliff must do the same for security: connect Wiz, CrowdStrike, Jira, GitHub, Snyk, and everything else into a unified remediation workspace.

The bar is high. Security teams handle credentials for systems that protect entire organizations. If we lose their trust once, we lose it forever. So integrations must be not just powerful, but provably secure and fully auditable.

---

## 2. Integration use cases

Every integration in Cliff serves one or more of these four purposes:

**Ingest** — Pull findings into the queue.
Connect to Wiz, Snyk, Tenable, Dependabot, SonarQube, or any scanner. Findings flow in through polling or webhooks, get normalized into Cliff's domain model, and land in the Queue ready for triage. This is the FindingSource adapter interface.

**Investigate** — Query external platforms during remediation.
When an agent enriches a finding, it might pull CVE details from NVD, check CrowdStrike for endpoint context, query GitHub for the affected code, or look up the asset owner in your CMDB. The workspace's AI agents call these integrations as tools during their reasoning. This maps to OwnershipContext and the new InvestigationContext adapter type.

**Act** — Create tickets, update statuses, close findings.
After the remediation planner builds a fix plan, Cliff creates a Jira ticket, assigns it, and tracks progress. When validation confirms the fix, Cliff closes the finding in the source system. This is the Ticketing and Validation adapter pair, extended with write-back capabilities.

**Enrich context** — Pull code, configs, and environment data.
For an AppSec finding, pull the affected repository from GitHub and let the agent read the vulnerable code. For a cloud misconfiguration, pull the Terraform state or cloud config. This gives agents the raw material they need for accurate remediation plans.

---

## 3. Design principles

### 3.1 MCP-native by default

The Model Context Protocol is the integration standard. Every external system connection in Cliff is either an MCP server or wrapped in one. This is not a bolt-on — it's the foundation.

Why MCP:

- **AI-native.** MCP servers expose tools, resources, and prompts that AI agents consume directly. No translation layer between "what the integration provides" and "what the agent needs."
- **Ecosystem leverage.** Hundreds of MCP servers already exist for GitHub, Jira, Slack, databases, cloud providers. Cliff users get these for free.
- **Community extensibility.** Anyone who can write an MCP server can extend Cliff. The protocol is standardized and well-documented.
- **Workspace isolation.** Each workspace process can connect to its own set of MCP servers with its own credentials, matching our per-workspace isolation architecture (ADR-0014).

The architecture:

```
┌──────────────────────────────────────────────────────────┐
│  Cliff Backend (FastAPI)                                │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Integration Manager                                 │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │ │
│  │  │ Registry │  │ Credential│  │  Audit Logger    │  │ │
│  │  │          │  │ Vault     │  │                  │  │ │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
│                          │                                │
│  ┌───────────────────────┼────────────────────────────┐  │
│  │  Workspace Runtime    │                             │  │
│  │                       ▼                             │  │
│  │  ┌─────────────────────────────────────────────┐   │  │
│  │  │  MCP Gateway (per-workspace)                │   │  │
│  │  │                                             │   │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌─────────┐      │   │  │
│  │  │  │ Builtin │ │ Managed │ │  User   │      │   │  │
│  │  │  │ Adapters│ │  MCPs   │ │  MCPs   │      │   │  │
│  │  │  └─────────┘ └─────────┘ └─────────┘      │   │  │
│  │  └─────────────────────────────────────────────┘   │  │
│  │                       │                             │  │
│  │  ┌────────────────────┼────────────────────────┐   │  │
│  │  │  OpenCode Process  │                        │   │  │
│  │  │                    ▼                        │   │  │
│  │  │  Orchestrator → Sub-Agents → MCP Tools      │   │  │
│  │  └─────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │   Wiz    │  │   Jira   │  │  GitHub  │
      │  (MCP)   │  │  (MCP)   │  │  (MCP)   │
      └──────────┘  └──────────┘  └──────────┘
```

### 3.2 Two planes, one contract

A key insight from enterprise security tool patterns: not everything should go through the LLM. Deterministic pipeline operations (scheduled finding sync, webhook ingestion, status write-back) and agentic investigation (interactive enrichment, reasoning about remediation) have fundamentally different reliability and auditability requirements.

Cliff uses two integration planes that share a single contract:

**Operational plane** — Deterministic connectors for ingestion, sync, normalization, state mapping, and upstream writes. These run on schedules or react to webhooks. No LLM involvement. Think: "every 15 minutes, poll Wiz for new findings and normalize them into the queue."

**Agentic plane** — MCP tools and resources for interactive investigation and enrichment. These are invoked by AI agents during workspace remediation. Think: "the enricher agent calls `wiz_get_asset_context` to understand the blast radius."

Both planes share:
- The same **canonical objects** (Finding, Asset, Identity, Evidence, External Reference)
- The same **four verbs** (collect, enrich, investigate, update)
- The same **credential vault** and **audit logger**
- The same **permission model**

The MCP side exposes those verbs as tools. The operational side exposes them as scheduled jobs and webhook handlers. One integration definition, two execution modes.

### 3.3 Capability minimization

Borrowed directly from the GitHub MCP Server's design: integrations should be capability-minimized by default.

- **Read-only first.** Every integration starts with read permissions only. Write capabilities (update finding status, create tickets) require explicit opt-in.
- **Toolset scoping.** Not all tools from an MCP server need to be exposed. Cliff allows enabling specific tool subsets per integration.
- **Action tiers.** Three tiers of connector actions:
  - **Tier 0 — Read-only.** Fetch findings, read asset context, list tickets. No approval needed.
  - **Tier 1 — Contextual enrichment.** Pull code, correlate identities. No approval needed but fully logged.
  - **Tier 2 — Mutation/write.** Create tickets, update statuses, close findings. Requires explicit human confirmation for sensitive writes and full parameter visibility.

This is not just a security model — it's a trust-building model. Users see exactly what Cliff can do before granting more power.

### 3.4 Three tiers of integrations

**Tier 1 — Community MCP servers (managed).** Leverage existing, battle-tested MCP servers from the ecosystem. GitHub's official MCP server (27K+ stars, 51 tools), Atlassian's official Jira/Confluence MCP server (25 tools with workflow transitions), and similar production-grade servers. Cliff manages their lifecycle — the user enables them through the Integrations page, provides credentials, and Cliff spawns/manages the process. We don't rebuild what already exists.

**Tier 2 — Thin Cliff wrappers.** For vendors that don't have open-source self-hostable MCP servers (e.g., Wiz's MCP is cloud-only/proprietary), we build lightweight MCP wrappers around their REST APIs. These are minimal — just enough to translate the vendor API into MCP tools. Written in Python, inline with the codebase, tested in CI.

**Tier 3 — User MCP servers.** Anything the user wants to connect. They provide the MCP server command or URL, and Cliff connects to it. No curation, no registry entry needed. Full power, user's responsibility. Like adding custom MCP servers in Claude Code's settings.

### 3.5 Security is the product

Every integration interaction is treated as a security event:

- **Encrypted credential storage.** API keys and tokens encrypted at rest using a key derived from a user-provided passphrase or system keyring. Never plaintext in SQLite.
- **Scoped permissions.** Each integration declares what it can do (read findings, write tickets, etc.). Agents can only use the permissions granted.
- **Full audit trail.** Every API call to an external system is logged with timestamp, workspace context, agent identity, action taken, and outcome. Users can review exactly what Cliff did and when.
- **No credential leakage to agents.** Agents call MCP tools by name. The MCP gateway injects credentials at the transport layer. The LLM never sees API keys in its context.
- **Principle of least privilege.** Workspace processes only get MCP connections relevant to their finding. A Wiz finding workspace doesn't get access to the Snyk MCP server unless explicitly needed.

### 3.6 Enterprise governance controls

Borrowed from Claude Code's managed-mcp.json pattern and Codex's trusted project model, Cliff implements three-tier configuration scoping:

- **System-managed integrations.** Configured at install time or by the administrator. Cannot be modified by workspace-level config. These are the "blessed" integrations.
- **Workspace-managed integrations.** Configured per-workspace based on the finding context. Cliff determines which integrations a workspace needs.
- **User-managed integrations.** Custom MCP servers added by the user. Subject to allowlist/denylist policy enforcement.

Policy enforcement follows Claude Code's model:
- **Allowlists** restrict which MCP server commands/URLs can be used
- **Denylists** block specific commands/URLs
- **Trust gates** require explicit approval before running a new MCP server for the first time

### 3.7 Easy to add, easy to audit

Adding a new integration should take minutes for managed MCPs (enable, paste credentials, done) and hours for custom adapters (implement interface, write tests, submit PR). The adding-an-adapter guide already exists — we're extending it with MCP patterns.

---

## 4. MCP Gateway: build vs. adopt

The MCP Gateway is the core integration runtime. Before building from scratch, we evaluated the existing open-source landscape.

### 4.1 Existing open-source MCP Gateway projects

| Project | Focus | License | Fit for Cliff |
|---------|-------|---------|-----------------|
| **Gate22** (aipotheosis-labs) | Function-level permissions, per-call audit logging, tool poisoning detection | Apache 2.0 | Best audit/permission model. Study for patterns. |
| **Lasso MCP Gateway** (lasso-security) | Credential sanitization, PII protection, token masking, reputation scoring | — | Best credential protection patterns. |
| **MCPProxy.go** (smart-mcp-proxy) | Docker isolation, OAuth 2.1/PKCE, quarantine for new servers, BM25 tool discovery | — | Best per-workspace isolation model. |
| **Fiberplane Gateway** (fiberplane) | Traffic inspection, real-time logging, web dashboard for captured traffic | — | Best observability/debugging patterns. |
| **Microsoft MCP Gateway** | Dual-plane (control + data), Azure RBAC, Kubernetes-native, session-aware routing | — | Good enterprise RBAC patterns but heavy on Azure/K8s. |
| **MCP Mesh** (decocms) | Encrypted token vault, RBAC per workspace/project, agent cost tracking | SUL | Best credential vault and workspace-scoped RBAC model. |
| **IBM ContextForge** | Federated discovery, multiple auth schemes, rate limiting, user-scoped OAuth | — | Good multi-auth and rate limiting patterns. |

### 4.2 Decision: build our own, informed by the best

None of the existing gateways are a drop-in fit for Cliff because:

1. **OpenCode integration.** Our gateway must generate per-workspace `opencode.json` configs and manage MCP server lifecycles tied to OpenCode workspace processes. No existing gateway understands this.
2. **Two-plane architecture.** We need both operational (deterministic) and agentic (MCP) execution. Existing gateways only handle the agentic plane.
3. **Inline simplicity.** We're choosing inline packaging (see decisions below) — the gateway lives inside the Cliff codebase, not as an external dependency.
4. **Security-specific audit requirements.** Our audit event model includes finding-level traceability, agent attribution, and policy decision logging that goes beyond what generic gateways provide.

However, we will heavily borrow patterns from:
- **Gate22** → Permission model and per-call audit event schema
- **Lasso** → Credential sanitization and PII detection in logs
- **MCPProxy.go** → Quarantine workflow for untrusted MCP servers and Docker isolation patterns
- **MCP Mesh** → Encrypted token vault design with workspace-scoped RBAC

---

## 5. OpenCode MCP integration: how it actually works

This section is critical because Cliff's workspace runtime (ADR-0014) runs per-workspace OpenCode processes. Understanding exactly how OpenCode handles MCP servers determines our gateway architecture.

### 5.1 OpenCode MCP configuration

OpenCode configures MCP servers via `opencode.json` under the `mcp` key:

```json
{
  "mcp": {
    "github": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-github", "--read-only"],
      "environment": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "resolved-at-startup"
      },
      "enabled": true,
      "timeout": 10000
    },
    "jira": {
      "type": "local",
      "command": ["npx", "-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"],
      "environment": {
        "ATLASSIAN_TOKEN": "resolved-at-startup"
      },
      "enabled": true,
      "timeout": 10000
    },
    "wiz": {
      "type": "local",
      "command": ["python", "-m", "cliff.integrations.wrappers.wiz"],
      "environment": {
        "WIZ_CLIENT_ID": "resolved-at-startup",
        "WIZ_CLIENT_SECRET": "resolved-at-startup"
      },
      "enabled": true,
      "timeout": 10000
    }
  }
}
```

Notice: GitHub and Jira use their official MCP servers (installed via npx). Only Wiz uses our thin wrapper. All credentials are resolved from the Vault before writing this file.

Key facts:
- **Local servers** (stdio transport) are child processes started via `command` array
- **Remote servers** use HTTP/SSE with static `headers` for auth
- Configuration is **static at startup** — adding/removing MCP servers requires restarting the OpenCode process
- OpenCode calls `tools/list` at init to discover available tools, then exposes them to agents alongside built-in tools

### 5.2 Per-workspace MCP configuration (the key insight)

OpenCode supports project-level config via `opencode.json` in the working directory. Since Cliff already creates per-workspace directories (`data/workspaces/<id>/`) with their own `opencode.json`, we can configure different MCP servers per workspace:

```
data/workspaces/
  ws-001/                          # Wiz finding workspace
    opencode.json                  # MCP: wiz + jira + github
    .opencode/agents/...
    context/...
  ws-002/                          # Snyk finding workspace
    opencode.json                  # MCP: snyk + jira + gitlab
    .opencode/agents/...
    context/...
```

Each workspace gets exactly the MCP servers relevant to its finding. A Wiz finding workspace gets the Wiz MCP server; a Snyk finding workspace gets the Snyk MCP server. Both get ticketing (Jira) and code context (GitHub/GitLab).

### 5.3 Credential injection flow

Cliff's MCP Gateway resolves credentials before writing the workspace's `opencode.json`:

```
1. Workspace created for Finding F-123 (source: Wiz)
         │
2. WorkspaceContextBuilder asks Integration Manager:
   "What integrations does a Wiz finding need?"
         │
3. Integration Manager returns: [wiz, jira, github]
         │
4. MCP Gateway resolves credentials from Vault:
   - wiz.client_id → decrypt → "abc123"
   - wiz.client_secret → decrypt → "secret456"
   - jira.api_token → decrypt → "jira-token-789"
   - github.token → decrypt → "ghp_xxx"
         │
5. Gateway generates workspace opencode.json with resolved credentials
   in environment variables (local servers) or headers (remote servers)
         │
6. OpenCode process starts with cwd=data/workspaces/ws-001/
   → reads opencode.json → starts MCP server child processes
   → discovers tools → agents can use them
```

**Important:** Credentials appear in the workspace `opencode.json` as resolved values (not placeholders) because OpenCode doesn't support vault integration. This means:
- Workspace `opencode.json` files are **never committed to git** (already in `.gitignore`)
- Workspace directories are **ephemeral** — cleaned up when workspace is closed
- File permissions are **restricted** to the Cliff process user
- The `opencode.json` is regenerated on every workspace process start (never stale)

### 5.4 OpenCode MCP limitations we must design around

| Limitation | Impact | Our mitigation |
|------------|--------|----------------|
| No runtime MCP reconfiguration | Can't add/remove MCP servers without restart | Keep config static per workspace lifetime. If integrations change, restart workspace process. |
| No auto-reconnection for idle remote servers | Long-idle workspaces may lose MCP connections | Use local (stdio) servers for reliability. For remote: implement keep-alive pings in gateway. |
| MCP server crash can hang OpenCode | Unstable servers break entire workspace | Wrap MCP servers in supervisor process with crash recovery. Monitor health. |
| Ignores `type: "resource"` in tool outputs | Only text/image content works | Ensure all our MCP servers return text content, not resource type. |
| No per-session MCP auth in serve mode | Multi-session sharing can't have different creds | We already use per-workspace processes, so this doesn't affect us. |

### 5.5 MCP server lifecycle tied to workspace lifecycle

```
Workspace opened → OpenCode process starts → MCP servers init → tools available
         │
Agents use tools during remediation (audited by gateway)
         │
Workspace idle (10 min default) → OpenCode process stops → MCP servers terminated
         │
Workspace reopened → new OpenCode process → fresh MCP servers → tools re-discovered
```

This is clean and maps perfectly to our existing `WorkspaceProcessPool` (ADR-0014 Layer 3). The MCP Gateway extends the pool to also manage MCP server health alongside OpenCode process health.

---

## 6. Credential management architecture

This is the most security-critical component. Here's how it works:

### 6.1 Encryption at rest

```
User provides credentials via Integrations page
         │
         ▼
┌─────────────────────────────────────┐
│  Credential Vault                   │
│                                     │
│  1. Generate per-credential IV      │
│  2. Encrypt with AES-256-GCM       │
│  3. Key from: system keyring        │
│     OR user passphrase (PBKDF2)     │
│     OR env var (Docker deployments) │
│  4. Store encrypted blob in SQLite  │
│  5. Never log, never return in API  │
└─────────────────────────────────────┘
```

Key derivation priority:
1. **System keyring** (GNOME Keyring, macOS Keychain, Windows Credential Manager) — best for desktop installs
2. **`CLIFF_CREDENTIAL_KEY` environment variable** — best for Docker/server deployments
3. **User passphrase** — fallback, prompted on first integration setup

### 6.2 Credential injection

Agents never see credentials. The flow:

```
Agent calls: mcp.tool("wiz_list_findings", filters={...})
         │
         ▼
MCP Gateway intercepts
         │
         ▼
Credential Vault decrypts API key for "wiz" integration
         │
         ▼
MCP Gateway injects auth header into outbound request
         │
         ▼
Wiz API response returned to agent (no credentials in payload)
```

### 6.3 Credential lifecycle

- **Creation:** User enters via Integrations page → encrypted → stored
- **Rotation:** User updates credentials → old encrypted blob replaced → all active workspace connections refreshed
- **Deletion:** User removes integration → encrypted blob deleted → active MCP connections terminated
- **Testing:** "Test connection" button validates credentials work before saving
- **Export:** Never. Credentials cannot be exported or viewed after initial entry.

---

## 7. Audit logging architecture

Every integration interaction produces an audit event:

### 7.1 Why "audit-grade" matters for Cliff

Audit is not just "logs exist." Per NIST SP 800-92, log management covers the full lifecycle: generating, transmitting, storing, analyzing, and disposing of log data. For Cliff, audit must support investigations, compliance reviews, least-privilege verification, and customer trust.

With MCP and agentic workflows, the model decides which tools to invoke and with what parameters — creating a new attack surface. OWASP's MCP Top 10 includes "Lack of Audit and Telemetry" as a core risk, calling for detailed logs of tool invocations, context changes, and user-agent interactions with immutable audit trails.

### 7.2 Audit event schema

```json
{
  "id": "evt_a1b2c3d4",
  "timestamp": "2026-03-31T14:23:45.123Z",
  "event_type": "integration.api_call",
  "correlation_id": "corr_x7y8z9",
  "workspace_id": "ws-12345",
  "finding_id": "finding-67890",
  "agent": "finding_enricher",
  "integration": {
    "id": "int-wiz-001",
    "provider": "wiz",
    "adapter_type": "finding_source"
  },
  "action": {
    "tool": "wiz_get_finding_details",
    "verb": "investigate",
    "action_tier": 0,
    "method": "GET",
    "endpoint": "/api/v1/findings/{id}",
    "parameters_hash": "sha256:abc123..."
  },
  "policy": {
    "decision": "allow",
    "policy_version": "v1",
    "approval_required": false,
    "approval_obtained": null
  },
  "result": {
    "status": "success",
    "http_status": 200,
    "duration_ms": 342,
    "response_size_bytes": 4521
  },
  "error": null
}
```

Key design choices in this schema:
- **correlation_id** links related events across retries and multi-step workflows
- **verb** (collect/enrich/investigate/update) maps to the integration contract
- **action_tier** (0/1/2) indicates risk level for policy evaluation
- **policy block** records the governance decision, not just the outcome
- **parameters_hash** — never raw parameter values (prevents credential leakage in logs)

### 7.3 What gets logged

- Every outbound API call to any external system
- Every MCP tool invocation (including parameters hash, never raw values)
- Credential access events (which credential was used, never the credential itself)
- Integration configuration changes (enabled, disabled, credentials updated)
- Failed authentication attempts
- Rate limiting events

### 7.4 Storage, integrity, and access

- Stored in a dedicated `audit_log` SQLite table (append-only, no UPDATE or DELETE)
- **Tamper-evidence:** Hash chain — each event includes the SHA-256 hash of the previous event, creating a verifiable chain. Any modification to historical events breaks the chain and is detectable.
- Queryable by workspace, integration, time range, event type, correlation ID
- Exportable as JSON or CSV for compliance (signed export bundles for forensic use)
- Retention configurable (default: 90 days, aligned with common compliance requirements)
- Clock synchronization enforced — timestamps use monotonic clock for duration, wall clock for absolute time. NTP sync recommended in deployment docs.
- Accessible via API and UI (new Audit tab in workspace sidebar)

---

## 8. MCP gateway architecture

The MCP Gateway is the core innovation — a per-workspace proxy that manages MCP server connections, injects credentials, enforces permissions, and logs everything. It lives inline in the Cliff codebase (not a separate package), informed by patterns from Gate22, Lasso, and MCPProxy.go.

### 8.1 How it works

When a workspace starts, the MCP Gateway:
1. Reads the workspace's finding metadata to determine which integrations are relevant
2. Starts or connects to the required MCP server processes
3. Registers available tools with the workspace's OpenCode process
4. Intercepts all tool calls, injecting credentials and logging events
5. Enforces permission boundaries (read-only vs read-write)

### 8.2 MCP server lifecycle

```
Integration enabled by user
         │
         ▼
MCP server config stored in registry
         │
         ▼
Workspace created for a finding from that integration
         │
         ▼
MCP Gateway starts MCP server process (stdio transport)
  OR connects to remote MCP server (HTTP/SSE transport)
         │
         ▼
Tools registered with OpenCode via opencode.json mcpServers config
         │
         ▼
Agents invoke tools → Gateway intercepts → credentials injected → call made
         │
         ▼
Workspace goes idle → MCP connections kept warm for timeout period
         │
         ▼
Workspace process stopped → MCP server processes terminated
```

### 8.3 Configuration format

MCP servers are configured in a format compatible with Claude Code and OpenCode:

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github", "--read-only"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${credential:github.token}"
      }
    },
    "jira": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"],
      "env": {
        "ATLASSIAN_TOKEN": "${credential:jira.oauth_token}"
      }
    },
    "wiz": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cliff.integrations.wrappers.wiz"],
      "env": {
        "WIZ_CLIENT_ID": "${credential:wiz.client_id}",
        "WIZ_CLIENT_SECRET": "${credential:wiz.client_secret}",
        "WIZ_API_URL": "${config:wiz.api_url}"
      }
    },
    "user-custom": {
      "type": "stdio",
      "command": "/path/to/custom-mcp-server",
      "args": [],
      "env": {}
    }
  }
}
```

Notice: GitHub and Jira use their official MCP servers directly — no Cliff custom code. Only Wiz uses our thin wrapper because Wiz's official MCP is cloud-only and not self-hostable.

The `${credential:...}` and `${config:...}` placeholders are resolved by the MCP Gateway at startup using the Credential Vault. The MCP server process receives real values; the config file never contains plaintext secrets.

---

## 9. Integration registry

The registry is how Cliff knows what integrations are available and how to configure them.

### 9.1 Registry entry schema

```json
{
  "id": "wiz",
  "name": "Wiz",
  "description": "Cloud security platform — import findings, investigate issues, update remediation status",
  "icon": "wiz.svg",
  "categories": ["finding_source", "investigation", "validation"],
  "tier": "builtin",
  "mcp_config": {
    "type": "stdio",
    "command": "cliff-mcp-wiz",
    "args": []
  },
  "credentials_schema": {
    "client_id": { "type": "string", "label": "Client ID", "required": true },
    "client_secret": { "type": "string", "label": "Client secret", "required": true, "secret": true },
    "api_url": { "type": "string", "label": "API URL", "required": false, "default": "https://api.wiz.io" }
  },
  "capabilities": {
    "finding_source": {
      "supports_webhook": true,
      "supports_polling": true,
      "severity_mapping": { "CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low" }
    },
    "investigation": {
      "tools": ["wiz_get_finding_details", "wiz_get_asset_context", "wiz_get_graph_relationships"]
    },
    "validation": {
      "tools": ["wiz_check_finding_status", "wiz_request_rescan"]
    }
  },
  "docs_url": "https://docs.cliff.dev/integrations/wiz",
  "setup_guide": "1. Create a service account in Wiz...",
  "permissions_required": ["read:findings", "read:assets", "write:findings.status"]
}
```

### 9.2 Registry sources and MCP discovery

1. **Builtin registry** — Ships with Cliff in `backend/cliff/integrations/registry/`. Contains entries for all Tier 1 adapters.
2. **Community registry** — A GitHub repository (`cliff/integration-registry`) with community-contributed entries. Users can opt-in to fetch from this.
3. **MCP discovery standard** — Cliff will participate in the emerging MCP server discovery protocol. As the standard matures, Cliff can discover compatible MCP servers automatically, similar to how OpenCode supports `.well-known/opencode` endpoint for organization-default servers.
4. **Local overrides** — Users can add custom entries in `data/integrations/` for Tier 3 user MCPs.

---

## 10. OAuth for self-hosted deployments

Some integrations (GitHub, Jira Cloud, Azure DevOps) require OAuth. Self-hosted tools can't use standard redirect flows because there's no public callback URL. Cliff supports two patterns:

**Standards alignment:** OAuth best practice has evolved significantly. Cliff aligns with RFC 9700 (OAuth 2.0 Security BCP), RFC 8252 (OAuth for Native Apps — use system browser, never embedded), and RFC 7636 (PKCE — mandatory for all flows).

### 10.1 OAuth authorization code + PKCE (preferred)

When a browser is available on the same machine as Cliff, use authorization code with PKCE via localhost redirect:

```
User clicks "Connect Wiz" in Integrations page
         │
         ▼
Cliff starts temporary HTTP server on 127.0.0.1:{random_port}
         │
         ▼
Browser opens Wiz auth URL with redirect_uri + PKCE challenge
         │
         ▼
User authorizes → browser redirects to localhost with auth code
         │
         ▼
Cliff exchanges code + PKCE verifier for tokens → encrypts → stores
         │
         ▼
Temporary HTTP server shuts down
```

### 10.2 Device authorization flow (RFC 8628)

For headless/Docker deployments and providers that support it:

```
User clicks "Connect GitHub" in Integrations page
         │
         ▼
Cliff requests device code from GitHub
         │
         ▼
UI shows: "Go to https://github.com/login/device and enter code: ABCD-1234"
         │
         ▼
User authorizes in their browser
         │
         ▼
Cliff polls GitHub for token (with exponential backoff)
         │
         ▼
Token received → encrypted → stored in Credential Vault
```

Note: GitHub's own OAuth documentation notes security drawbacks of device flow (phishing/impersonation risks), which is why authorization code + PKCE is preferred when a browser is available.

### 10.3 Client credentials flow (for service accounts)

For scheduled ingestion and background sync (operational plane), use OAuth client credentials:

```
Cliff uses stored client_id + client_secret
         │
         ▼
Requests access token from provider (e.g., Wiz tokens last ~24h, CrowdStrike ~30min)
         │
         ▼
Caches token in memory with TTL → auto-refreshes before expiry
```

### 10.4 API key / token flow (simplest)

For providers that support static API tokens (most self-hosted tools):

```
User pastes API key in Integrations page → encrypted → stored
```

All three flows end at the same place: an encrypted credential in the Vault, ready for the MCP Gateway to inject.

---

## 11. First integrations — the priority list

Based on what security teams actually use day-to-day, here's the prioritized integration list:

### Tier 1 — Must-have (ship in first integration release)

| Integration | Type | Approach | Why first |
|-------------|------|----------|-----------|
| **GitHub** | Context enrichment | Official MCP server (`github/github-mcp-server`, 27K+ stars, 51 tools) — zero custom code | Pull code for AppSec findings. Read CODEOWNERS for ownership. |
| **Jira** | Ticketing | Official Atlassian MCP server (`atlassian/atlassian-mcp-server`, 25 tools) — zero custom code | Dominant ticketing system. Every enterprise has it. |
| **Wiz** | FindingSource + Investigation | Thin Python wrapper around Wiz REST API (Wiz's MCP is cloud-only/proprietary) | Largest cloud security platform. Most findings originate here. |

### Tier 2 — High priority (next quarter)

| Integration | Type | Approach | Why |
|-------------|------|----------|-----|
| **Snyk** | FindingSource | Check for community MCP server; thin wrapper if needed | Major AppSec scanner. Different finding shape from Wiz. |
| **CrowdStrike** | Investigation | Thin wrapper (likely no existing MCP server) | Endpoint context for runtime findings. |
| **ServiceNow** | Ticketing | Check for community MCP server | Enterprise alternative to Jira. |
| **PagerDuty** | Notification | Check for community MCP server | Escalation for critical findings. |

### Tier 3 — Ecosystem growth

| Integration | Type | Why |
|-------------|------|-----|
| **Tenable** | FindingSource | Infrastructure vulnerability scanning. |
| **SonarQube** | FindingSource | Code quality and security findings. |
| **AWS Security Hub** | FindingSource | Native cloud findings aggregation. |
| **Azure Defender** | FindingSource | Microsoft cloud security. |
| **Slack** | Notification | Team communication for remediation updates. |
| **GitLab** | Context enrichment | Alternative to GitHub for code context. |
| **Terraform** | Context enrichment | Infrastructure-as-code context. |
| **CMDB (generic)** | OwnershipContext | Asset ownership resolution. |

---

## 12. The integration roadmap

This roadmap extends the existing Cliff roadmap (Stages 1-4) with integration-specific phases. It starts after Stage 4 (MVP ship) but some foundation work begins during Stage 3.

### Phase I-0: Integration foundation (during Stage 3)

> Lay the groundwork while agent orchestration is being completed.

**Credential Vault**
- [ ] Design credential encryption module (`backend/cliff/integrations/vault.py`)
- [ ] Implement AES-256-GCM encryption with per-credential IVs
- [ ] Support key derivation from: system keyring, env var, user passphrase
- [ ] Migrate existing `IntegrationConfig.config` field to use encrypted storage
- [ ] Add "test connection" endpoint
- [ ] Write ADR-0015: Credential management architecture
- [ ] 20+ unit tests for encryption, key derivation, rotation

**Audit logging**
- [ ] Design audit event schema and `audit_log` table
- [ ] Implement async audit logger (non-blocking, queue-based)
- [ ] Add audit events for integration CRUD operations
- [ ] Add API endpoint: `GET /api/audit?workspace_id=...&integration=...&since=...`
- [ ] Write ADR-0016: Integration audit logging
- [ ] 15+ unit tests

**Integration registry v1**
- [ ] Define registry entry JSON schema
- [ ] Create `backend/cliff/integrations/registry/` with builtin entries
- [ ] Update Integrations page to show registry entries with setup guides
- [ ] Support credential schema rendering (dynamic forms based on `credentials_schema`)
- [ ] 10+ unit tests

**Exit criteria:** Credentials are encrypted at rest. Every integration action is audited. The Integrations page shows a catalog of available integrations with guided setup.

---

### Phase I-1: MCP gateway (after Stage 3, parallel with Stage 4)

> The core integration runtime. This is the hardest and most important phase.

**MCP Gateway core**
- [ ] Design MCP Gateway component (`backend/cliff/integrations/gateway.py`)
- [ ] Implement MCP server process management (start, stop, health check)
- [ ] Implement credential placeholder resolution (`${credential:...}` → real values)
- [ ] Implement tool call interception and audit logging
- [ ] Support stdio transport (local MCP servers)
- [ ] Support HTTP/SSE transport (remote MCP servers)
- [ ] Write ADR-0017: MCP Gateway architecture

**Workspace integration**
- [ ] Extend `WorkspaceContextBuilder` to determine required integrations per workspace
- [ ] Extend `WorkspaceProcessPool` to manage MCP server processes alongside OpenCode
- [ ] Generate workspace-specific `opencode.json` with MCP server configs
- [ ] Implement MCP connection lifecycle tied to workspace lifecycle (start/idle/stop)
- [ ] Add workspace context route: `GET /workspaces/{id}/integrations` (active connections)

**Permission model**
- [ ] Define permission scopes per integration (read, write, admin)
- [ ] Implement permission enforcement in MCP Gateway
- [ ] Add permission configuration to Integrations page
- [ ] Default to least-privilege (read-only unless user explicitly grants write)

**Testing**
- [ ] 30+ unit tests (mocked MCP servers)
- [ ] Integration tests with a test MCP server
- [ ] E2E test: workspace → MCP tool call → audit event

**Exit criteria:** A workspace can connect to MCP servers, agents can call tools, credentials are injected securely, every call is audited, and permissions are enforced.

---

### Phase I-2: First real integrations

> Prove the architecture with the three highest-value integrations. Key principle: **use existing MCP servers wherever possible.** We don't rebuild what the ecosystem already provides.

**GitHub — use official MCP server (zero custom code)**
- [ ] Registry entry for `github/github-mcp-server` (27K+ stars, MIT, 51 tools)
- [ ] Install: `npx -y @modelcontextprotocol/server-github` (stdio transport)
- [ ] Auth: GitHub Personal Access Token (env var `GITHUB_PERSONAL_ACCESS_TOKEN`)
- [ ] Capabilities used by Cliff agents: `read_file` (CODEOWNERS, code), `search_code` (vulnerable patterns), `get_code_scanning_alerts`, `get_dependabot_alerts`, `list_commits`, `create_issue` / `create_pull_request` (future automated fixes)
- [ ] Enable `--read-only` mode by default (Tier 0 action); write tools opt-in
- [ ] Integration test: workspace agent reads a file from a repo via MCP tool
- [ ] 5+ integration tests

**Jira — use official Atlassian MCP server (zero custom code)**
- [ ] Registry entry for `atlassian/atlassian-mcp-server` (official, 25 tools)
- [ ] Two modes: Jira Cloud (OAuth 2.1 via Atlassian Rovo) and Jira Server/Data Center (API token via `cosmix/jira-mcp` fallback)
- [ ] Capabilities used by Cliff agents: `create_issue`, `update_issue`, `transition_issue` (workflow state changes), `add_comment`, `search_issues` (JQL)
- [ ] Link tickets to workspaces: store external key + URL in SidebarState
- [ ] Integration test: workspace agent creates a Jira issue from remediation plan
- [ ] 5+ integration tests

**Wiz — thin wrapper required (Wiz MCP is cloud-only/proprietary)**
- [ ] Implement `cliff-mcp-wiz` — lightweight Python MCP server wrapping Wiz REST API
- [ ] Why: Wiz's official MCP server is cloud-only and proprietary, not usable for self-hosted Cliff
- [ ] Tools to implement: `wiz_list_findings`, `wiz_get_finding`, `wiz_get_asset_context`, `wiz_update_finding_status`, `wiz_check_finding_status`
- [ ] Auth: client credentials flow (client_id + client_secret → 24h token, auto-refresh)
- [ ] Keep it minimal — just translate Wiz REST API into MCP tools, no business logic
- [ ] Registry entry with credential schema and setup guide
- [ ] 15+ unit tests, 5+ integration tests (with Wiz sandbox or mocked)

**Exit criteria:** A Wiz finding can flow through Cliff end-to-end: ingested from Wiz (via wrapper), enriched with GitHub code context (via official MCP), remediation planned, Jira ticket created (via official MCP), and finding status updated in Wiz after validation. All fully audited.

---

### Phase I-3: User MCP servers

> Let users bring their own integrations.

**User MCP configuration**
- [ ] Add "Custom MCP server" option to Integrations page
- [ ] Support stdio config (command + args + env vars)
- [ ] Support HTTP/SSE config (URL + auth headers)
- [ ] Credential management for custom server environment variables
- [ ] MCP server health checking and connection status display
- [ ] Tool discovery: show available tools from connected MCP server

**MCP server management UI**
- [ ] List active MCP connections per workspace
- [ ] Show available tools with descriptions
- [ ] Test tool execution from Integrations page
- [ ] View audit log filtered by custom MCP server

**Safety guardrails**
- [ ] Sandboxed execution for stdio MCP servers (resource limits, network restrictions)
- [ ] Tool call rate limiting
- [ ] Response size limits
- [ ] Timeout enforcement
- [ ] Clear warnings about running untrusted MCP servers

**Exit criteria:** A user can connect any MCP server to Cliff, their workspace agents can use its tools, and everything is audited with appropriate safety guardrails.

---

### Phase I-4: Webhook ingestion

> Move from polling to push for real-time finding ingestion.

**Webhook receiver**
- [ ] Add webhook endpoint: `POST /api/webhooks/{integration_id}`
- [ ] HMAC signature verification per integration
- [ ] Payload validation against integration-specific schemas
- [ ] Finding creation/update from webhook payloads
- [ ] Deduplication logic (same finding from multiple webhooks)
- [ ] Retry queue for failed processing

**Supported webhook sources**
- [ ] Wiz webhook events
- [ ] GitHub Dependabot / Code Scanning alerts
- [ ] Snyk webhook notifications
- [ ] Generic webhook format (user-defined payload mapping)

**Webhook management UI**
- [ ] Show webhook URL per integration
- [ ] Display webhook secret for configuration in source system
- [ ] Webhook event log (received, processed, failed)
- [ ] Pause/resume webhook processing

**Exit criteria:** Findings arrive in Cliff in near-real-time via webhooks. No polling delay for supported sources.

---

### Phase I-5: Advanced capabilities

> Polish and power-user features.

**Integration analytics dashboard**
- [ ] API call volume per integration over time
- [ ] Error rates and latency percentiles
- [ ] Most-used tools per workspace/agent
- [ ] Credential expiration warnings

**Bulk operations**
- [ ] Import findings from CSV/JSON (manual upload)
- [ ] Bulk status update across multiple findings in source system
- [ ] Scheduled finding sync (cron-based polling)

**Integration testing framework**
- [ ] Dry-run mode for new integrations (simulate without real API calls)
- [ ] Integration health dashboard
- [ ] Automated credential validation on schedule

**Community integration toolkit**
- [ ] `cliff-mcp-template` repository for building custom MCP servers
- [ ] Integration development guide with examples
- [ ] Integration testing harness
- [ ] Submission process for community registry

**Exit criteria:** Cliff has a mature, observable, and extensible integration platform that the community can build on.

---

## 13. Technical implementation details

### 13.1 New database tables

```sql
-- Encrypted credential storage
CREATE TABLE credential (
    id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES integration_config(id),
    key_name TEXT NOT NULL,           -- e.g., "api_token", "client_secret"
    encrypted_value BLOB NOT NULL,     -- AES-256-GCM encrypted
    iv BLOB NOT NULL,                  -- Per-credential initialization vector
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    UNIQUE(integration_id, key_name)
);

-- Audit log (append-only)
CREATE TABLE audit_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- integration.api_call, integration.config_change, etc.
    workspace_id TEXT,
    finding_id TEXT,
    agent TEXT,                        -- Which agent triggered the action
    integration_id TEXT,
    provider TEXT,
    action TEXT NOT NULL,              -- Tool name or action description
    parameters_hash TEXT,              -- SHA-256 of parameters (never raw values)
    result_status TEXT,                -- success, error, timeout
    http_status INTEGER,
    duration_ms INTEGER,
    error_message TEXT,
    correlation_id TEXT,                -- Links related events across retries/workflows
    policy_decision TEXT,               -- allow/deny + policy version
    prev_hash TEXT,                     -- SHA-256 of previous event (tamper-evidence chain)
    metadata TEXT                       -- JSON blob for additional context
);

CREATE INDEX idx_audit_workspace ON audit_log(workspace_id, timestamp);
CREATE INDEX idx_audit_integration ON audit_log(integration_id, timestamp);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);

-- MCP server configuration
CREATE TABLE mcp_server_config (
    id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES integration_config(id),
    transport TEXT NOT NULL,            -- stdio, http_sse
    command TEXT,                       -- For stdio: command to run
    args TEXT,                          -- JSON array of arguments
    url TEXT,                           -- For http_sse: server URL
    env_template TEXT,                  -- JSON: env vars with ${credential:...} placeholders
    health_check_interval_s INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 13.2 New Python modules

```
backend/cliff/integrations/
    __init__.py
    vault.py              # Credential Vault — encryption, key derivation, storage
    audit.py              # Audit Logger — async event recording
    registry.py           # Integration Registry — discover and describe integrations
    gateway.py            # MCP Gateway — process management, credential injection, interception
    permissions.py        # Permission model — scope enforcement
    oauth/
        __init__.py
        device_flow.py    # RFC 8628 device authorization flow
        localhost_flow.py # Localhost redirect fallback
    wrappers/
        __init__.py
        wiz/              # Thin MCP wrapper for Wiz REST API (only vendor without self-hostable MCP)
    registry/
        github.json       # Registry entry — uses official github/github-mcp-server (zero custom code)
        jira.json         # Registry entry — uses official atlassian/atlassian-mcp-server (zero custom code)
        wiz.json          # Registry entry — uses our thin wrapper (cliff-mcp-wiz)
        ...
    webhooks/
        __init__.py
        receiver.py       # Webhook endpoint handler
        validators.py     # HMAC signature verification
        parsers/          # Per-integration payload parsers
```

### 13.3 New API routes

```
# Integration management
GET    /api/integrations                     # List all integrations (registry + configured)
GET    /api/integrations/{id}                # Get integration details
POST   /api/integrations/{id}/configure      # Save credentials and enable
PUT    /api/integrations/{id}/credentials    # Update credentials
DELETE /api/integrations/{id}                # Remove integration
POST   /api/integrations/{id}/test           # Test connection

# OAuth flows
POST   /api/integrations/{id}/oauth/device   # Start device flow
GET    /api/integrations/{id}/oauth/status    # Poll device flow status
POST   /api/integrations/{id}/oauth/localhost # Start localhost redirect flow

# MCP management
GET    /api/integrations/mcp/servers          # List all MCP server configs
POST   /api/integrations/mcp/servers          # Add custom MCP server
GET    /api/integrations/mcp/servers/{id}/tools  # List tools from MCP server

# Workspace integrations
GET    /api/workspaces/{id}/integrations      # Active integrations for workspace
GET    /api/workspaces/{id}/integrations/tools # Available tools in workspace

# Webhooks
POST   /api/webhooks/{integration_id}         # Receive webhook events
GET    /api/webhooks/{integration_id}/events   # List received events

# Audit
GET    /api/audit                              # Query audit log
GET    /api/audit/export                       # Export as JSON/CSV
GET    /api/workspaces/{id}/audit              # Workspace-scoped audit log
```

### 13.4 Frontend changes

**Integrations page (major redesign)**

The current Integrations page is a simple list. The new version becomes an integration marketplace:

- **Catalog view** — Grid of available integrations with icons, descriptions, and "Connect" buttons
- **Connected integrations** — List of active integrations with status indicators, last sync time, and "Configure" / "Disconnect" buttons
- **Integration detail panel** — Setup guide, credential form (rendered from `credentials_schema`), permission toggles, OAuth flow UI
- **Custom MCP server dialog** — Add arbitrary MCP server with command/URL configuration

**Workspace sidebar (new audit tab)**

- **Integrations section** — Shows which integrations are active for this workspace
- **Audit trail** — Chronological list of all external API calls made by agents in this workspace

**Settings page (new security section)**

- **Encryption key management** — Configure credential encryption key source
- **Audit retention** — Set audit log retention period
- **MCP server policies** — Allow/deny list for MCP server commands

---

## 14. Security hardening checklist

Before each integration phase ships, verify:

- [ ] No credentials stored in plaintext anywhere (SQLite, logs, config files, environment)
- [ ] Audit log captures every outbound API call
- [ ] MCP server processes run with minimal OS privileges
- [ ] Credential injection happens at transport layer, never in agent context
- [ ] OAuth tokens are encrypted at rest with proper key management
- [ ] Webhook endpoints validate HMAC signatures before processing
- [ ] Rate limiting on all external API calls
- [ ] Timeout enforcement on all MCP tool calls
- [ ] No credential values in error messages or stack traces
- [ ] API response sanitization (strip auth headers from logged responses)
- [ ] Dependency audit for all MCP server npm/pip packages
- [ ] OWASP top-10 review for webhook endpoints

---

## 15. Competitive analysis: what makes Cliff different

**vs. DefectDojo** — DefectDojo is a vulnerability management hub with import/export. Cliff is AI-native: agents investigate, plan, and act. DefectDojo imports scan results; Cliff reasons about them.

**vs. SOAR platforms (Splunk SOAR, Palo Alto XSOAR)** — SOAR platforms are playbook-driven automation for security operations. Cliff is conversational and adaptive. No pre-built playbooks needed — the AI determines the remediation path per finding.

**vs. Custom scripts** — Most security teams wire together Python scripts, Slack bots, and Jira automation. Cliff replaces this fragile glue with a structured, auditable platform.

**The Cliff differentiator:** MCP-native integration means every connected tool becomes a first-class capability for AI agents. Your Wiz context, GitHub code, and Jira tickets are all available in a single reasoning loop. No other remediation tool offers this.

---

## 16. Success metrics

| Metric | Target (6 months post-launch) |
|--------|-------------------------------|
| Integrations in registry | 15+ |
| Community-contributed MCP adapters | 5+ |
| Average time to connect a new integration | Under 5 minutes |
| Audit log coverage | 100% of external API calls |
| Credential encryption coverage | 100% of stored secrets |
| Zero plaintext credential exposures | 0 incidents |

---

## 17. Resolved decisions

1. **MCP server packaging → Inline.** Builtin adapters ship inline with the Cliff codebase in `backend/cliff/integrations/adapters/`. Simplicity wins — no separate PyPI packages, no version-lock headaches. The adapters are Python modules that implement the adapter interface and optionally expose MCP tools via stdio. If an adapter grows complex enough to warrant extraction, we can do that later.

2. **Multi-tenant credential isolation → Deferred.** Community Edition is single-user. We will not design for multi-tenant credential scoping now. When the multi-user/team edition comes, we'll add per-user credential namespacing. The current Credential Vault design is simple and single-tenant.

3. **MCP server discovery → Participate in emerging standard.** Cliff will adopt the MCP server discovery protocol as it matures. We'll also support OpenCode's `.well-known/opencode` pattern for organization-default server discovery. The builtin + community registry covers us until the standard solidifies.

4. **Webhook security in Docker → Document when we get there.** Webhook endpoints in containerized deployments need network accessibility from source systems. This is a deployment-time concern. We'll create Docker deployment documentation with networking guidance (port exposure, reverse proxy patterns, HMAC verification) when we implement Phase I-4 (Webhook Ingestion).

5. **Rate limiting → Defer until real.** We will not implement rate limiting in the initial integration phases. When we encounter real rate-limit issues with external APIs during Phase I-2 (first integrations), we'll add per-integration rate limiting informed by actual vendor limits. Premature optimization here would add complexity without proven benefit.

## 18. Remaining open questions

1. **Supply chain integrity for community MCP servers** — Should we require signed artifacts for community-contributed integrations? SLSA attestation? Sigstore? Deferred until the community registry grows beyond our ability to manually review.

2. **Confused deputy mitigation** — MCP's authorization model warns about confused deputy attacks when acting as a proxy. If Cliff brokers OAuth to third-party APIs, we need per-client consent to avoid authorization code theft. Design this before Phase I-2.

3. **Token lifetime handling** — Different vendors have wildly different token lifetimes (Wiz ~24h, CrowdStrike ~30min). The credential vault needs a TTL-aware caching layer with automatic refresh. Spec this during Phase I-0.

---

## Appendix A: Research sources

This strategy was informed by research into:

**Protocol and standards:**
- **MCP specification** (modelcontextprotocol.io) — Protocol architecture, transport mechanisms, tool/resource/prompt primitives
- **MCP security best practices** (modelcontextprotocol-security.io) — Confused deputy, token passthrough, tool poisoning risks
- **OWASP MCP Top 10** — Audit/telemetry gaps, tool poisoning, schema poisoning
- **OAuth RFCs** — RFC 9700 (Security BCP), RFC 8252 (Native Apps), RFC 7636 (PKCE), RFC 8628 (Device Flow)
- **NIST SP 800-92** — Computer security log management lifecycle

**AI coding agents:**
- **Claude Code integration model** — MCP server management, managed-mcp.json policies, allowlist/denylist governance, enterprise desktop extensions
- **OpenCode** (github.com/anomalyco/opencode) — MCP config via opencode.json, local/remote server types, per-project config, OAuth auto-detection, `.well-known/opencode` discovery
- **OpenAI Codex** — MCP server support, trusted project scoping, OAuth 2.1 patterns

**MCP Gateway landscape:**
- **Gate22** (aipotheosis-labs) — Function-level permissions, per-call audit logging, tool poisoning detection
- **Lasso MCP Gateway** (lasso-security) — Credential sanitization, PII protection, reputation scoring
- **MCPProxy.go** (smart-mcp-proxy) — Docker isolation, quarantine workflow, OAuth 2.1/PKCE
- **Fiberplane Gateway** — Traffic inspection, real-time logging dashboard
- **Microsoft MCP Gateway** — Dual-plane architecture, Azure RBAC, session-aware routing
- **MCP Mesh** (decocms) — Encrypted token vault, workspace-scoped RBAC

**Security tools:**
- **DefectDojo** — Vulnerability management hub, connector patterns, scan import/sync
- **Cortex/TheHive** — Analyzer isolation via job boundary (input.json/output.json), responder patterns
- **GitHub MCP Server** — Capability minimization (toolsets, read-only mode, lockdown), lockdown controls

**Enterprise patterns:**
- **Backstage** — Plugin isolation, backend-over-wire communication, independent deployment
- **CrowdStrike Falcon** — OAuth client-credentials flow, 30-min token TTL, proxy considerations
- **Wiz** — Service account model, 24h token lifetime, minimal scope recommendations
- **SLSA / Sigstore** — Supply chain integrity, artifact provenance, tamper-resistant signing logs

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **MCP** | Model Context Protocol — open standard for connecting AI applications to external tools and data |
| **MCP Server** | A process that exposes tools, resources, and prompts via the MCP protocol |
| **MCP Gateway** | Cliff component that manages MCP connections, injects credentials, and logs interactions |
| **Credential Vault** | Encrypted credential storage module in Cliff |
| **Adapter** | Cliff interface for connecting to a specific type of external system |
| **Integration** | A configured connection to an external system, backed by an adapter or MCP server |
| **Registry** | Catalog of available integrations with metadata, credential schemas, and setup guides |
| **Stdio transport** | MCP communication via stdin/stdout with a local process |
| **HTTP/SSE transport** | MCP communication via HTTP with Server-Sent Events for streaming |
| **Device flow** | OAuth authorization flow for devices without browsers (RFC 8628) |
| **PKCE** | Proof Key for Code Exchange — prevents authorization code interception (RFC 7636) |
| **Operational plane** | Deterministic integration execution (polling, webhooks, scheduled sync) without LLM |
| **Agentic plane** | AI-driven integration execution via MCP tools during workspace remediation |
| **Action tier** | Risk classification: 0=read-only, 1=enrichment, 2=mutation/write |
| **Confused deputy** | Attack where an MCP proxy grants unauthorized access via shared credentials |
| **Tool poisoning** | Attack where a malicious MCP server returns harmful tool definitions |
