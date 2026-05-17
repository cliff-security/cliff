# ADR-0022: App-Level Agent Execution and Conversational Shell

**Date:** 2026-04-06
**Status:** Proposed

## Context

Cliff currently runs AI agents only inside workspace contexts. Each workspace gets an isolated OpenCode process (ADR-0014) with finding-specific context, MCP server configs, and agent templates. This model works well for remediation workflows but leaves a gap: there is no way to run AI-driven tasks at the **app level** — outside a workspace.

Three concrete needs have surfaced:

1. **Finding normalization.** Users need to ingest raw findings from diverse scanners (Wiz, Snyk, Trivy, Semgrep, custom tools). Hardcoding per-vendor normalizers doesn't scale for a community product. An LLM can extract structured fields from any vendor's format into Cliff's `FindingCreate` schema — but there's no workspace to run it in.

2. **Finding collection.** Users want to say "connect to Wiz and fetch all critical findings from the last 7 days." This requires calling MCP tools (the Wiz wrapper already exists) and processing the results — but again, there's no workspace context because we're populating the Queue, not remediating a specific finding.

3. **Conversational app shell.** Cliff is an AI-native product, but currently the only conversational interface is inside workspaces. Users have expressed interest in chatting with the app itself: "configure a Jira integration", "show me all unresolved critical findings", "upload these findings from my Snyk export." This would make the entire product chat-first, with pages as views into the conversation's work.

The singleton OpenCode process (port 4096) already exists — it starts at FastAPI lifespan for health checks and settings API access. It has no workspace-specific context but can execute general-purpose prompts.

## Decision

### Part 1: App-level agent execution (implement now)

Use the existing singleton OpenCode process for lightweight, stateless agent tasks that don't belong to any workspace. The first use case is finding normalization.

**Design:**
- The singleton process on port 4096 handles app-level agent tasks
- Tasks are stateless — no persistent session, no sidebar, no agent run log
- A **dedicated normalizer agent** (`.opencode/agents/finding-normalizer.md`) defines the extraction contract — a focused prompt that takes raw vendor data and outputs `FindingCreate` JSON. This follows the same pattern as workspace agents (Phase 6a) but lives at the app level
- The FastAPI route (`POST /api/findings/ingest`) sends the prompt, parses the structured response, and calls the existing `create_finding` DB function
- No new process pool, no new architecture — reuse what exists

**Cost optimization:**
- The normalizer agent is a structured extraction task, not open-ended reasoning. The prompt should be tight: schema definition + raw data in, JSON out — no chain-of-thought, no tool use
- Use the cheapest available model. The singleton process inherits the app's configured model, but the normalizer prompt should be designed to work well even with smaller/faster models (e.g., GPT-4.1-mini, Claude Haiku)
- Batch-friendly: the route should accept a list of raw findings in a single call to amortize prompt overhead when ingesting bulk exports
- **For bulk ingest (>50 findings), the synchronous endpoint is replaced by an async chunked job system. See [ADR-0023](0023-async-chunked-finding-ingestion.md)**
- The prompt template should include 1-2 few-shot examples of normalized output to reduce tokens wasted on format negotiation
- **[ADR-0023](0023-async-chunked-finding-ingestion.md) extends this** with pre-processing token estimation, per-request model override, and dry-run mode for cost preview before committing to a bulk ingest

**Constraints:**
- App-level tasks must be lightweight (normalization, classification, summarization)
- **Long-running tasks (bulk normalization of 50+ findings) must use the async job system ([ADR-0023](0023-async-chunked-finding-ingestion.md)) to avoid blocking the singleton process for extended periods**
- Heavy multi-step workflows belong in workspaces
- No MCP tools in the singleton process — it doesn't have per-integration configs
- If a task needs MCP tools (e.g., fetching findings from Wiz), it needs a temporary process with resolved MCP configs — design this when the need becomes concrete

### Part 2: Conversational app shell (design later, build post-MVP)

A future iteration could add a persistent chat interface at the app level — not tied to any workspace. This would enable:

- **Finding ingestion via conversation:** "Here's a JSON export from Snyk, normalize and import these findings"
- **Collector configuration:** "Set up a Wiz collector that fetches critical findings daily"
- **Integration management:** "Configure Jira with these credentials and test the connection"
- **Cross-finding queries:** "Show me all findings affecting the payments service"
- **Triage assistance:** "Prioritize these 50 new findings by exploitability and blast radius"

**This requires careful design because:**
- The app-level chat needs its own OpenCode process with a different agent personality than workspace agents (general assistant vs. remediation specialist)
- It needs access to MCP tools for integration management, but with different scoping than workspace processes
- The interaction grammar changes: workspaces follow `ask → run → summarize → persist → decide next`, but app-level chat is more exploratory
- The frontend layout needs to accommodate a persistent chat alongside the existing page navigation — not replace it
- Session persistence and context management differ from workspace chat (longer-lived, cross-cutting concerns)

**Do not build this incrementally.** A half-built app-level chat alongside the workspace chat will feel disconnected. Write a focused design document before implementation.

## Consequences

**Part 1 (app-level agent execution):**
- **Easier:** Finding ingestion works with any scanner format via LLM normalization — no per-vendor code
- **Easier:** Community contributors don't need to write normalizer code for their scanner
- **Easier:** Uses existing singleton process — no new infrastructure
- **Harder:** Token cost per finding at ingest (mitigated: small structured extraction task, use cheapest model)
- **Harder:** LLM normalization may occasionally misparse edge cases (mitigated: validate against Pydantic schema, reject invalid extractions)

**Part 2 (conversational shell — future):**
- **Easier:** Product becomes fully AI-native — every interaction can be conversational
- **Easier:** Onboarding is natural — users describe what they want in plain language
- **Harder:** Two chat contexts (app + workspace) need coherent but distinct personalities
- **Harder:** Significant frontend architecture work (layout, routing, session management)
- **Harder:** MCP tool access at app level needs its own scoping and permission model
