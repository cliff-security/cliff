# PRD-000c: Integrations framework (as-built)

**Status:** Approved (as-built)
**Author:** Product team (bootstrap)
**Date:** 2026-04-09
**Approver:** @galanko (CEO)

---

## Problem statement

A remediation copilot is only useful if it connects to the tools security teams already use — scanners (Wiz, Snyk, Tenable), ticketing (Jira, ServiceNow), and context sources (CMDB, code repos). Without integrations, users must manually copy-paste data between systems. Cliff's integration framework lets agents access external tools during remediation via MCP (Model Context Protocol) servers — community or thin wrappers — without custom code for each vendor.

## User persona

**Security team lead / admin** — sets up the Cliff instance, configures which scanners and ticketing systems to connect, and manages API credentials. Not necessarily the same person who uses workspaces daily.

## User stories

### Story 1: Browse available integrations

**As an** admin, **I want to** see which integrations are available and their status, **so that** I know what I can connect.

**Given** I navigate to the Integrations page,
**When** the page loads,
**Then** I see all available integrations organized by type (finding source, ticketing, validation, context) with their status (connected, available, coming soon).

**The user should feel:** Informed — "I can see what's possible and what's already connected."

### Story 2: Configure a new integration

**As an** admin, **I want to** set up a new integration by providing credentials, **so that** agents can use it during remediation.

**Given** I click "Set up" on an available integration,
**When** I fill in the credential form (dynamic per integration) and click save,
**Then** the credentials are encrypted and stored, and the integration appears as configured.

**The user should feel:** Confident — "Setup was straightforward and my credentials are secure."

### Story 3: Test the connection

**As an** admin, **I want to** test that an integration is working, **so that** I don't find out it's broken when an agent tries to use it.

**Given** I've configured an integration,
**When** I click "Test connection",
**Then** I see a clear pass/fail result with details.

**The user should feel:** Assured — "I know this works before I rely on it."

## What exists today

- **MCP-native architecture (ADR-0015):** Integrations run as MCP servers, not custom code
- **Integration registry:** JSON manifests define vendor config, MCP setup, capabilities, action tiers
- **Credential vault (ADR-0016):** AES-256-GCM encrypted storage with PBKDF2 key derivation
- **MCP Gateway (ADR-0018):** Per-workspace MCP configs resolved from vault + registry
- **Connection testers:** Dedicated test functions validate credentials independently of MCP
- **Health monitoring:** Background polling of integration health with status indicators
- **Wiz integration:** Fully working — findings ingestion, MCP server for remediation queries
- **Integrations page UI:** Browse registry, configure credentials, test connection, health status
- **Finding normalization (ADR-0022):** LLM-powered ingestion normalizes any scanner format
- **Async chunked ingest (ADR-0023):** Job-based background processing for large finding sets

## Known gaps

- [ ] Ingest progress UI — backend job system exists but no frontend progress bar/cancel
- [ ] Jira write-back — registry entry exists but no workspace UI for ticket creation
- [ ] Status write-back to source systems (Wiz tool exists, not wired into workspace flow)
- [ ] Snyk and Tenable thin MCP wrappers
- [ ] Operational plane — scheduled sync/polling (deferred, ADR-0020 downgraded to Proposed)

## Scope boundaries

**In scope for MVP:** Configure, test, and use one real integration (Wiz). MCP-native for all future integrations.
**Out of scope:** Webhook ingestion, scheduled polling, multi-tenant credential isolation, integration marketplace.

---

_As-built PRD — documents what exists as of 2026-04-09. Not a future spec._
