# ADR-0020: Two-Plane Integration Architecture

**Date:** 2026-03-31
**Status:** Proposed
**Note:** Downgraded from Accepted (2026-04-06). The agentic plane is implemented and working. The operational plane (polling, webhooks, sync) has zero implementation and no concrete timeline. Designing the shared contract now creates phantom constraints — revisit when operational plane work begins.

## Context

Cliff integrations serve two fundamentally different execution modes:

1. **Deterministic operations.** Poll Wiz every 15 minutes for new findings. Receive a webhook from GitHub Dependabot. Sync ticket status from Jira nightly. Update a finding's status in the source system after validation. These are scheduled, predictable, and must succeed reliably without human intervention.

2. **Agentic operations.** The finding enricher calls `wiz_get_asset_context` to understand blast radius. The remediation planner calls `github_read_file` to inspect vulnerable code. The owner resolver calls `jira_search_issues` to find related tickets. These are AI-driven, interactive, and happen during workspace remediation sessions.

Conflating these into a single execution model creates problems:

- **Reliability mismatch.** Scheduled sync must retry on failure, handle rate limits gracefully, and never depend on an LLM being available. MCP tool calls during agentic reasoning have different timeout and retry semantics.
- **Audit semantics differ.** A scheduled poll is a background operation attributed to "system." An agent's MCP tool call is attributed to a specific workspace, finding, and sub-agent. The audit event schema needs to capture both.
- **Permission model differs.** Background sync needs service-account credentials with narrow scopes. Agentic operations may need broader read access for investigation. Writing (ticket creation, status updates) may need human approval in the agentic plane but not in the operational plane (where the approval was given upfront via configuration).

Enterprise security tool patterns (DefectDojo connectors, CrowdStrike Falcon TA, SIEM ingestion pipelines) all separate deterministic ingestion/sync from interactive investigation.

## Decision

Adopt a two-plane integration architecture where both planes share the same integration contract, credential vault, and audit system, but execute independently.

**Operational plane** — Deterministic connectors for ingestion, sync, and background operations.
- Runs as FastAPI background tasks or scheduled jobs
- No LLM involvement
- Service-account credentials (OAuth client credentials or API tokens)
- Retry with exponential backoff, rate-limit awareness
- Idempotent operations (safe to re-run)
- Audit events attributed to "system" with schedule/webhook context

**Agentic plane** — MCP tools for interactive investigation and enrichment during workspace remediation.
- Runs within per-workspace OpenCode processes via MCP servers (ADR-0014, ADR-0015)
- LLM decides which tools to invoke and with what parameters
- Workspace-scoped credentials resolved by MCP Gateway (ADR-0018)
- Audit events attributed to specific workspace, finding, and sub-agent
- Action tier enforcement: read-only default, write requires opt-in (ADR-0015)

**Shared integration contract.** Both planes implement the same four verbs:
- `collect` — Pull data from external system into Cliff
- `enrich` — Add context to an existing entity (finding, asset, workspace)
- `investigate` — Query external system for analysis (may be interactive)
- `update` — Write back to external system (status change, ticket creation)

**Shared infrastructure:**
- Same Credential Vault (ADR-0016) for both planes
- Same audit logging system (ADR-0017) for both planes
- Same integration registry for both planes
- A single integration (e.g., Wiz) can be used by both planes simultaneously: operational plane polls for new findings, agentic plane investigates specific findings during remediation

## Consequences

- **Easier:** Finding ingestion (operational) and finding investigation (agentic) are decoupled. Scheduled sync doesn't depend on workspace processes. Agent reasoning doesn't depend on sync schedules.
- **Easier:** Each plane can evolve independently. We can ship webhook ingestion (operational) without changing the agentic plane, and vice versa.
- **Easier:** Audit trail is cleaner because each event has unambiguous attribution — either system-triggered (operational) or agent-triggered (agentic) with full workspace context.
- **Easier:** Permission model is clearer. Operational plane actions are pre-approved via configuration. Agentic plane actions follow the three-tier model with potential human-in-the-loop for writes.
- **Harder:** Two execution paths means two sets of error handling, retry logic, and health monitoring.
- **Harder:** The same credential may be used by both planes simultaneously (e.g., Wiz API key for both polling and workspace investigation). Token refresh must handle concurrent access. Mitigated by the Vault's caching layer with TTL-aware refresh.
- **Harder:** Testing must cover both planes and their interactions (e.g., a finding ingested by the operational plane is then investigated by the agentic plane in a workspace).
