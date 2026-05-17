# PRD-000e: Agent pipeline (as-built)

**Status:** Approved (as-built)
**Author:** Product team (bootstrap)
**Date:** 2026-04-09
**Approver:** @galanko (CEO)

---

## Problem statement

Remediating a vulnerability requires multiple specialized tasks: understanding the CVE, finding who owns the affected system, assessing exposure, planning the fix, and verifying it worked. No single AI model can do all of these well in one prompt. Cliff's agent pipeline breaks remediation into 5 specialized sub-agents, each with a focused prompt, structured output contract, and clear role — turning a complex, ambiguous task into a guided, repeatable process.

## User persona

**Security engineer** — working inside a Workspace. They trigger agents one at a time via action chips, review each output, and decide when to proceed. They're the human in the loop — agents advise, the user decides.

## User stories

### Story 1: Enrich a finding

**As a** security engineer, **I want to** run the Finding Enricher, **so that** I understand the CVE details, severity, exploit availability, and affected versions before I act.

**Given** I'm in a workspace with a finding,
**When** I click "Enrich finding",
**Then** the enricher agent runs, returns structured data (CVE, CVSS, exploits, affected versions), and updates the sidebar Summary + Evidence sections.

**The user should feel:** Informed — "Now I understand what I'm dealing with."

### Story 2: Identify the owner

**As a** security engineer, **I want to** run the Owner Resolver, **so that** I know who is responsible for the affected system.

**Given** a finding has been enriched,
**When** I click "Find owner",
**Then** the owner resolver identifies the responsible team/person with evidence, and updates the sidebar Owner section.

**The user should feel:** Directed — "I know who to talk to."

### Story 3: Assess exposure

**As a** security engineer, **I want to** run the Exposure Analyzer, **so that** I understand reachability, internet-facing status, and blast radius.

**Given** I'm investigating a finding,
**When** I click "Check exposure",
**Then** the exposure analyzer assesses the risk context and updates the sidebar Evidence section.

**The user should feel:** Clear-eyed — "I know how bad this could get."

### Story 4: Plan the fix

**As a** security engineer, **I want to** run the Remediation Planner, **so that** I have a step-by-step fix plan with a definition of done.

**Given** I understand the finding and its context,
**When** I click "Build remediation plan",
**Then** the planner produces a fix plan, mitigations, and definition of done, and updates the sidebar Plan + DoD sections.

**The user should feel:** Confident — "I have a clear path forward."

### Story 5: Validate the fix

**As a** security engineer, **I want to** run the Validation Checker after deploying a fix, **so that** I can confirm it worked and safely close the finding.

**Given** a fix has been deployed,
**When** I click "Validate closure",
**Then** the validator checks the fix status and recommends close or reopen, updating the sidebar Validation section.

**The user should feel:** Assured — "The fix is verified. I can close this with confidence."

## What exists today

- **5 sub-agents** with Jinja2 templates rendered with workspace context:
  1. Finding Enricher — CVE details, severity, exploits
  2. Owner Resolver — team/person identification with evidence
  3. Exposure Analyzer — reachability, blast radius, criticality
  4. Remediation Planner — fix plan, mitigations, definition of done
  5. Validation Checker — fix verification, close/reopen recommendation
- **Orchestrator template** — pipeline state tracking with checklist
- **Structured output contracts** — per-agent Pydantic schemas with JSON validation
- **Agent executor** — sends prompt to OpenCode, collects SSE, parses, persists to context + sidebar + DB
- **Sidebar mapper** — read-merge-write maps output to sidebar without data loss
- **Pipeline orchestrator** — `suggest_next()` logic, plan-validate retry loop (max 3)
- **Execution API** — POST execute (202 + background), GET suggest-next, POST cancel
- **Stall detection** — activity events for SSE streaming, handles tool-call scenarios
- **Permission system** — auto-approve read-tier, wait for user on bash/edit/mcp (backend only)
- **E2E tests** — 5 tests with real OpenCode + LLM

## Known gaps

- [ ] Permission approval UI — tool use requests not surfaced to user (backend done, frontend pending)
- [ ] Orchestrator agent not exposed in action chips (only 5 hardcoded)
- [ ] No incremental streaming of agent progress to frontend
- [ ] Agent feedback loop — no way for user to say "this output was wrong"
- [ ] Autonomous pipeline mode — user must manually trigger each agent

## Scope boundaries

**In scope for MVP:** 5 agents, user-triggered, structured output, sidebar persistence, pipeline suggestion.
**Out of scope:** Autonomous chains, agent feedback/learning, custom agent creation, multi-model routing.

---

_As-built PRD — documents what exists as of 2026-04-09. Not a future spec._
