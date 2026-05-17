# ADR-0007: Domain Model Design

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff manages a vulnerability remediation lifecycle. We need a data model that captures findings, the work done on them, agent interactions, and outcomes.

The core user flow is: **finding appears in queue -> user opens workspace -> agents enrich/plan/validate -> ticket created -> finding closed**.

## Decision

Define these core entities:

- **Finding** — A vulnerability from a scanner. States: `new` -> `triaged` -> `in_progress` -> `remediated` -> `validated` -> `closed`. Can also be `exception` (accepted risk).
- **Workspace** — A remediation session tied to one Finding. States: `open` -> `waiting` -> `ready_to_close` -> `closed` (can reopen).
- **Message** — A chat message within a Workspace. Roles: `user`, `assistant`, `system`, `agent`.
- **AgentRun** — A single sub-agent execution. States: `queued` -> `running` -> `completed` | `failed` | `cancelled`.
- **SidebarState** — Structured workspace context (summary, evidence, owner, plan, definition of done, ticket link, validation). One per Workspace, updated after each agent run.
- **TicketLink** — Reference to an external ticket (Jira, GitHub Issue, etc.).
- **ValidationResult** — Outcome of a validation check. States: `not_started` -> `pending` -> `fixed` | `still_active` | `uncertain`.
- **AppSetting** — Key-value app configuration.
- **IntegrationConfig** — Adapter configuration (type, provider, enabled, credentials).

See `docs/architecture/domain-model.md` for complete field definitions.

## Consequences

- **Easier:** Clear state machines make the UI predictable and testable.
- **Easier:** SidebarState as a separate entity means agent results are persisted structurally, not just as chat text.
- **Harder:** State transitions must be enforced at the service layer. Invalid transitions should raise errors.
- **Harder:** Schema migrations needed as the model evolves. Using numbered SQL scripts from the start.
