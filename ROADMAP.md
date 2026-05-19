# Cliff Roadmap

> **Convention:** Every phase must have automated tests passing before it is considered complete. Run `cd backend && uv run pytest -v` and `cd backend && uv run ruff check cliff/ tests/` before marking a phase done.

## Phase 0: Decisions & Setup (Complete)

Lock the MVP boundaries before writing code.

- [x] Define MVP scope (vulnerability remediation copilot, single-user, self-hosted)
- [x] Lock technical decisions (FastAPI, React+Vite, SQLite, OpenCode, Docker)
- [x] Create repository structure
- [x] Write Architecture Decision Records (ADRs)
- [x] Document domain model, adapter interfaces, and agent pipeline
- [x] Write ROADMAP.md

**Exit criteria:** A new contributor can read the docs and understand what to build, how, and why.

---

## Phase 1: OpenCode Spike (Complete)

Prove the OpenCode engine works behind a browser chat.

- [x] Pin OpenCode version (`.opencode-version`) and create download script
- [x] Create OpenCode project config (`opencode.json`) and custom agent
- [x] Create FastAPI backend skeleton with OpenCode process manager
- [x] Implement OpenCode HTTP client (sessions, messages, streaming)
- [x] Implement API routes (health, sessions, chat with SSE)
- [x] Create minimal React frontend spike (chat UI with SSE consumer)
- [x] Create dev runner script (`scripts/dev.sh`)
- [x] Update ADR-0001 (submodule → binary dependency)
- [x] Manual validation: health, session create, session list via curl
- [x] Backend test suite (28 tests): config, models, engine client, process, routes
- [x] Lint clean (ruff check passes)
- [x] End-to-end tests (10 tests): health, sessions, chat, error handling with real OpenCode

**Exit criteria:** One minimal web page can start an OpenCode session, send a prompt, and stream the response back.

---

## Phase 2: App Shell (Complete)

Create the product frame — all five pages as navigable shells.

- [x] Initialize React + Vite + Tailwind project in `frontend/`
- [x] Add routing for Queue / Workspace / History / Integrations / Settings
- [x] Create app layout (nav, top bar, content area)
- [x] Add global design tokens and shared component primitives
- [x] Create base API client (TanStack Query + fetch)
- [x] Add markdown rendering system for result cards
- [x] Create page shells with Stitch-matching UI (populated with demo data)
- [x] Set up dev proxy (Vite -> FastAPI)
- [x] Adopt Stitch design system "Serene Sentinel" (ADR-0011)
- [x] Lint clean + build passes

**Exit criteria:** All five pages exist as shells. App is navigable. Theme is coherent.

---

# Stages 1–4: Parallel Execution Plan

> Phases 0–2 were sequential. From here on, work is organized into **stages** that maximize parallelism. Within each stage, tracks run concurrently. A stage completes when all its tracks are done.

```
Stage 1:  Phase 3 ──────────────┐
          Phase 6a (agents) ─────┤  (parallel — no deps between them)     ✅ ALL COMPLETE
          Phase 9a (docker) ─────┘
                                 │
Stage 2:  Phase 4 (Queue) ──────┤
          Phase 5 (Workspace) ───┤  (parallel — all need Phase 3 only)    ✅ ALL COMPLETE
          Phase 8 (History) ─────┘
                                 │
Stage 3:  Phase 6b (orchestr.) ──┤  (needs Phase 5)                       ← CURRENT
          Phase 7 (Tickets) ─────┘  (needs Phase 6b)
                                 │
Stage 4:  Phase 9b (ship) ───────┘  (needs everything)
```

**Critical path:** Phase 3 → Phase 5 → Phase 6b → Phase 7 → Phase 9b

---

## Stage 1: Foundation

Three parallel tracks with no dependencies between them. Stage 2 is blocked until all three complete.

### Phase 3: Persistence & Domain Model

Make the product stateful. Full vertical slice — backend schema, APIs, and tests.

- [x] Set up SQLite with WAL mode
- [x] Create migration system (numbered SQL scripts)
- [x] Implement schema for all entities (Finding, Workspace, Message, AgentRun, SidebarState, TicketLink, ValidationResult, AppSetting, IntegrationConfig)
- [x] Implement Finding CRUD API endpoints
- [x] Implement Workspace CRUD API endpoints
- [x] Implement Message storage and retrieval
- [x] Implement AgentRun storage
- [x] Implement SidebarState persistence
- [x] Tests for all CRUD endpoints

**Exit criteria:** Reloading the app preserves all state. All CRUD endpoints tested.

### Phase 6a: Agent Definitions (Complete)

Define the five cyber sub-agents. No code dependencies — just configs and prompts.

- [x] Define OpenCode agent configs for all 5 sub-agents (`.opencode/agents/`)
- [x] Define I/O contracts (input schema, output schema, sidebar field mapping)
- [x] Write agent prompts for Finding Enricher, Owner Resolver, Exposure Analyzer, Remediation Planner, Validation Checker
- [x] Jinja2 template engine renders agent prompts with finding context at workspace creation
- [x] Orchestrator template includes pipeline state tracking (`[x]`/`[ ]` checklist)
- [x] Each sub-agent has strict JSON output contract

**Exit criteria:** All 5 agent configs exist with documented I/O contracts.

### Phase 9a: Docker Skeleton

Build the container infrastructure. No dependency on app features.

- [x] Multi-stage Dockerfile (Node build -> Python + Go runtime)
- [x] Supervisord config for FastAPI + OpenCode processes
- [x] Docker Compose example with volume mounts
- [x] Environment variable handling (ports, data dir, model config)
- [x] Health check endpoint integration (`/health`)

**Exit criteria:** `docker compose up` builds and starts the app (feature-incomplete is fine).

---

## Stage 2: Features

Three full vertical slices (backend + frontend + wiring) that run in parallel. All depend on Phase 3 only.

### Phase 4: Queue

First usable page — the entry point for remediation work.

- [x] Findings list/table with columns: title, severity, asset, owner, status, updated
- [x] Filtering by severity, status, source
- [ ] Search by title, asset, CVE
- [x] Sort by severity, updated, status
- [x] "Solve" button creates/opens a Workspace for the Finding
- [x] Status badges and severity indicators
- [x] Data from FindingSource fixture adapter
- [ ] "Why this matters" preview on hover/expand

**Exit criteria:** User can land on Queue, browse findings, and open one into a Workspace. All backed by real APIs.

### Phase 5: Solve Workspace v1 (Complete)

The product center — chat-led remediation with persistent structured state.

- [x] Workspace page layout: top bar + center chat + right sidebar
- [x] Top bar: finding title, severity badge, status, action buttons
- [x] Chat thread: message list with user/assistant/agent roles
- [x] Chat input with send button
- [x] Suggested action chips ("Enrich finding", "Find owner", "Build plan")
- [x] Agent run cards (running state, spinner, status)
- [x] Markdown result cards for agent outputs
- [x] Persistent sidebar: Summary, Evidence, Owner, Plan, Definition of Done, Ticket, Validation
- [x] Sidebar auto-updates after each agent run
- [x] Activity timeline (chronological list of actions)
- [x] Connect chat to OpenCode via FastAPI orchestrator
- [x] **Isolated workspace runtime** (ADR-0014): each workspace gets its own directory + OpenCode process
- [x] Workspace directory with finding-specific context files (CONTEXT.md, finding.json, agent definitions)
- [x] Per-workspace OpenCode process pool with port allocation, idle cleanup, crash recovery
- [x] Workspace-scoped API routes for sessions, chat, and context
- [x] Frontend wired to workspace-scoped chat routes

**Exit criteria:** User can run at least one agent from chat, see the running state, get results, and see sidebar update. All state persisted. Each workspace runs in isolation.

### Phase 8: History — Superseded (Q02 / 2026-05-19)

> **Status:** Superseded. The standalone History page was removed in
> the Q02 batch fix (IMPL-0021). Closed findings now scroll into view
> at the bottom of `/issues` and are reachable from the same surface
> users already know. The `/history` route redirects to `/issues` for
> bookmark compatibility. The original shipped surface area (list,
> filter, search, replay, reopen, export-markdown) is preserved here
> for the historical trail.

- [x] History page with list of completed Workspaces
- [x] Filter: open vs completed, by finding, asset, owner, date range
- [x] Search across finding titles, agents used, outcomes
- [x] Summary card per workspace (finding, outcome, agents run, ticket)
- [x] Full chat replay for any past workspace
- [x] Reopen a past workspace for continued work
- [x] Export workspace summary as markdown

**Exit criteria (historical):** Completed work is searchable and readable. Past workspaces can be reopened. All backed by real APIs.

---

## Stage 3: Agent Integration & Tickets

Sequential within this stage — Phase 6b first, then Phase 7. Depends on Stage 2 (specifically Phase 5).

### Phase 6b: Agent Orchestration

Wire the agent definitions from Phase 6a into the workspace from Phase 5. The workspace runtime infrastructure (ADR-0014 Layers 0-4) is complete — agents now run in isolated workspace directories with finding-specific context.

- [x] Agent output parser — extract structured JSON from LLM responses with lenient fallbacks
- [x] Per-agent Pydantic schemas — validate enrichment, ownership, exposure, plan, validation output
- [x] Sidebar mapper — read-merge-write pattern maps agent output to sidebar without data loss
- [x] Agent executor — core engine: send prompt, collect SSE response, parse, persist to context + sidebar + DB
- [x] Pipeline orchestrator — `suggest_next()` with remediate-verify-retry loop (max 3)
- [x] Execution API — POST execute (202 + background), GET suggest-next, POST cancel
- [x] ADR-0021: Agent execution model (direct invocation, advisory pipeline, filesystem checkpoints)
- [x] Stall detection + activity events for SSE streaming (handles tool-call scenarios)
- [x] E2E tests — 5 tests with real OpenCode + real LLM (enricher execution, pipeline advance, progress callback)
- [ ] Handle `permission.asked` events — surface agent tool-use approval to the user (trust-building UX)

**Exit criteria:** A single finding can flow through all five agents and reach validated closure.

### Phase 7: Ticket Workflow

Turn remediation plans into actionable tickets. Depends on Phase 6b (needs agent output).

- [ ] Ticket preview panel in Workspace sidebar
- [ ] "Create ticket" action using mock Ticketing adapter
- [ ] "Update ticket" action for status changes
- [ ] Ticket state visible in sidebar (key, status, assignee, link)
- [ ] Close/reopen logic tied to ticket + validation state
- [ ] Link ticket into History entries
- [ ] Request approval placeholder (for future enterprise edition)

**Exit criteria:** Workspace can produce a ticket draft, create it (mock), and reference it during closure.

---

## Stage 4: Polish & Ship

Final packaging. Depends on everything above.

### Phase 9b: Packaging Finalization

- [ ] Startup migration runner
- [ ] Seed demo data mode (`CLIFF_DEMO=true`)
- [ ] Install documentation
- [ ] Upgrade documentation
- [ ] First tagged release (v0.1.0-alpha)

**Exit criteria:** `docker run -p 8000:8000 cliff` starts the full app. Demo data works. Config survives restart.

---

## Future (Post-MVP)

These are explicitly **not in the MVP** but are on the horizon:

- Multi-user / team edition with RBAC
- SSO / enterprise authentication
- Real adapter integrations (Tenable, Wiz, Snyk, Jira, ServiceNow, GitHub)
- Webhook-driven finding ingestion (push, not just pull)
- Scheduled scanning and auto-triage
- Plugin system for custom agents
- Approval workflows for enterprise compliance
- PostgreSQL support for larger deployments
- Cloud SaaS edition
