# ADR-0017: Integration Audit Logging

**Date:** 2026-03-31
**Status:** Accepted (with simplification note)
**Note:** Hash-chain tamper evidence (prev_hash, event_hash, verify_chain) is over-engineered for a single-user community edition (ADR-0009). Structured audit logging is valuable and stays. The hash-chain should be removed — it solves an enterprise compliance requirement we don't have yet. Re-add when building multi-user/enterprise edition.

## Context

Cliff integrations interact with systems that protect organizations — vulnerability scanners, ticketing platforms, code repositories, cloud security platforms. Every interaction is a security event. If we can't prove exactly what Cliff did, when, and why, enterprises won't trust us.

The challenge is amplified by agentic workflows: the AI model decides which MCP tools to invoke and with what parameters. OWASP's MCP Top 10 identifies "Lack of Audit and Telemetry" as a core risk. NIST SP 800-92 defines audit-grade log management as covering the full lifecycle: generating, transmitting, storing, analyzing, and disposing of log data.

We considered three approaches:

1. **Application-level logging only (Python logging module).** Simple but unstructured, mixed with debug logs, no tamper evidence, no queryable storage.
2. **External log aggregation (ELK, Splunk forwarding).** Enterprise-grade but adds infrastructure dependencies inappropriate for a self-hosted single-user tool.
3. **Dedicated append-only audit table in SQLite with structured events.** Queryable, tamper-evident via hash chaining, exportable for compliance, no external dependencies.

## Decision

Implement a dedicated integration audit logging system with an append-only `audit_log` table in SQLite, structured event schema, hash-chain tamper evidence, and async non-blocking writes.

Key design choices:

1. **Append-only storage.** The `audit_log` table supports INSERT only. No UPDATE or DELETE operations. This is enforced at the repository layer, not just by convention.

2. **Structured event schema.** Every event includes:
   - **Who:** workspace ID, finding ID, agent identity (which sub-agent triggered the action)
   - **What:** integration ID, provider, tool name, verb (collect/enrich/investigate/update), action tier (0=read, 1=enrich, 2=mutate)
   - **Why:** linked finding/workspace, workflow step context
   - **Policy:** governance decision (allow/deny), policy version, whether human approval was required and obtained
   - **Result:** success/error/timeout, HTTP status, duration, response size
   - **Tracing:** correlation ID linking related events across retries and multi-step workflows
   - **Never logged:** raw credential values, full request/response payloads with sensitive data. Parameters are stored as SHA-256 hashes.

3. **Hash-chain tamper evidence.** Each event includes `prev_hash` — the SHA-256 hash of the previous event. This creates a verifiable chain. Any modification to historical events breaks the chain and is detectable via a simple verification query.

4. **Async non-blocking writes.** Audit logging must never slow down agent execution. Events are queued in-process and written asynchronously. If the queue is full, events are written synchronously as a fallback (never dropped).

5. **Clock discipline.** Timestamps use wall clock for absolute time (ISO 8601 with timezone) and monotonic clock for duration measurement. Deployment docs will recommend NTP sync for environments where audit logs must correlate with external system logs.

6. **Retention and export.** Configurable retention period (default 90 days). Export as JSON or CSV for compliance. Signed export bundles for forensic use.

7. **Queryable via API and UI.** `GET /api/audit` with filters for workspace, integration, time range, event type, correlation ID. Workspace sidebar shows audit trail for the current workspace.

## Consequences

- **Easier:** Every external API call is traceable to a specific workspace, finding, and agent. Security teams can review exactly what Cliff did.
- **Easier:** Hash-chain tamper evidence gives users confidence that audit logs haven't been modified. This is a concrete trust signal for enterprise adoption.
- **Easier:** Correlation IDs allow tracing multi-step remediation workflows end-to-end (enrichment → planning → ticket creation → validation → status update).
- **Easier:** No external dependencies — audit logging works out-of-the-box in any deployment.
- **Harder:** Append-only storage means the SQLite database grows continuously. Mitigated by configurable retention and periodic cleanup of events older than the retention period.
- **Harder:** Async writes mean there's a small window where an event could be lost if the process crashes between queuing and writing. Acceptable for a single-user tool; enterprise edition would add write-ahead guarantees.
- **Harder:** Hash-chain verification is O(n) over the chain length. Mitigated by index on timestamp and periodic chain verification rather than per-query verification.
