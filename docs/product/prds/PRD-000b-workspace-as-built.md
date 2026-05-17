# PRD-000b: Workspace — remediation copilot (as-built)

**Status:** Approved (as-built)
**Author:** Product team (bootstrap)
**Date:** 2026-04-09
**Approver:** @galanko (CEO)

---

## Problem statement

Once a security engineer decides to remediate a finding, the process is manual and fragmented: research CVE details in one tool, find the asset owner in another, write a fix plan in a document, create a ticket in Jira, and verify the fix after deployment. This takes hours per finding and requires deep expertise. Cliff's Workspace is the product center — a chat-led AI copilot that guides the user through the entire remediation lifecycle from enrichment to validated closure.

## User persona

**Security engineer** — has identified a vulnerability and needs to remediate it. May lack deep knowledge of the specific CVE or the affected system's ownership. Needs AI assistance to research, plan, and validate — but ultimately makes the decisions.

## User stories

### Story 1: Chat with the copilot

**As a** security engineer, **I want to** chat with an AI assistant about my finding, **so that** I can ask questions and get help without leaving the workspace.

**Given** I've opened a workspace for a finding,
**When** I type a message and send it,
**Then** I receive a streamed AI response with context about my specific finding.

**The user should feel:** Supported — "I have an expert assistant who knows my finding."

### Story 2: Run specialized agents

**As a** security engineer, **I want to** trigger specialized AI agents (enrich, find owner, check exposure, plan fix, validate), **so that** each step of remediation is handled by a purpose-built expert.

**Given** I'm in a workspace,
**When** I click an action chip (e.g., "Enrich finding"),
**Then** the corresponding agent runs, shows progress, and delivers structured results that persist to both the chat and the sidebar.

**The user should feel:** In control — "I choose what runs and when. Each agent does one thing well."

### Story 3: Track progress in the sidebar

**As a** security engineer, **I want to** see all accumulated context (summary, evidence, owner, plan, ticket, validation) in a persistent sidebar, **so that** I always know where I am in the remediation process.

**Given** agents have produced outputs,
**When** I look at the sidebar,
**Then** I see the latest state for each category, accumulated across all agent runs.

**The user should feel:** Oriented — "I can see the full picture at a glance, not just chat history."

### Story 4: Isolated workspace per finding

**As a** security engineer, **I want** each finding's workspace to be isolated, **so that** context from one finding never leaks into another.

**Given** I have multiple open workspaces,
**When** I switch between them,
**Then** each has its own chat history, agent results, sidebar state, and AI context.

**The user should feel:** Safe — "My workspaces are independent. Nothing gets mixed up."

## What exists today

- **Layout:** Top bar (finding title, severity, status, actions) + center chat + right sidebar
- **Chat:** Full message thread with user/assistant/agent roles, markdown rendering, streaming
- **Action chips:** 5 quick actions — Enrich finding, Find owner, Check exposure, Build remediation plan, Validate closure
- **Agent execution:** Each chip triggers a dedicated sub-agent with structured JSON output
- **Sidebar:** 7 persistent sections — Summary, Evidence, Owner, Plan, Definition of Done, Ticket, Validation
- **Dual persist:** Every agent result goes to both chat timeline AND sidebar (enforced by architecture)
- **Workspace isolation (ADR-0014):** Each workspace gets its own directory (`data/workspaces/<id>/`), its own OpenCode process (ports 4100-4199), finding-specific context files, and rendered agent templates
- **Process pool:** Concurrent workspaces, idle timeout (10 min), crash recovery, port management
- **Pipeline orchestrator:** Suggests next agent, supports retry loops (plan → validate → retry up to 3x)

## Known gaps

- [ ] Permission approval UI — agents can request tool use (bash, edit, MCP) but no UI surfaces these requests yet (backend plumbing done in PR #34)
- [ ] Ticket workflow — no "Create ticket" action or ticket panel in sidebar (Phase 7)
- [ ] Real-time agent progress — agents run fully before response renders (no incremental streaming)
- [ ] Orchestrator agent — template exists but not exposed in action chips

## Scope boundaries

**In scope for MVP:** Chat, 5 agents, sidebar persistence, workspace isolation, pipeline orchestration.
**Out of scope:** Multi-user collaboration, real-time co-editing, voice input, autonomous agent chains (user must trigger each step).

---

_As-built PRD — documents what exists as of 2026-04-09. Not a future spec._
