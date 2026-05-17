# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Cliff is a self-hosted cybersecurity remediation copilot. It ingests vulnerability findings, enriches them with AI agents, and guides users through planning, ticketing, validating, and closing remediations — all from a chat-led web workspace.

Built on the [OpenCode](https://github.com/anomalyco/opencode) engine. Single-user community edition. AGPL-3.0 licensed.

## Architecture

| Layer | Technology | Location |
|-------|-----------|----------|
| Frontend | React + TypeScript + Vite + Tailwind | `frontend/` |
| Backend | FastAPI (Python 3.11+) | `backend/` |
| AI Engine | OpenCode (Go) — binary dependency, pinned in `.opencode-version` | managed subprocess |
| Workspace Runtime | Per-workspace OpenCode processes with isolated context (ADR-0014) | `backend/cliff/workspace/`, `backend/cliff/engine/pool.py` |
| Database | SQLite (single file) | `data/cliff.db` |
| Deployment | Single Docker container, port 8000 | `docker/` |

See `docs/architecture/overview.md` for the full system diagram and `docs/adr/0014-workspace-runtime-architecture.md` for the workspace isolation architecture.

## Design System: "The Serene Sentinel"

The UI follows the Stitch-generated "Ethos Security" design system (Stitch project `12683083125265338263`). See `docs/adr/0011-stitch-design-system.md` for the decision record.

| Aspect | Choice |
|--------|--------|
| Creative direction | "Editorial Assurance" — calm, authoritative, gallery-like |
| Color mode | Light mode default |
| Primary color | `#4d44e3` (indigo) |
| Background | `#f8f9fa` |
| Headlines font | Manrope (600-800) |
| Body/labels font | Inter (400-600) |
| Icons | Google Material Symbols Outlined |
| Color tokens | See `frontend/tailwind.config.ts` (65+ tokens from Stitch) |
| Mockup reference | `frontend/mockups/html/*.html` and `frontend/mockups/screenshots/*.png` |

**Core design rules:**
- **No-Line Rule:** Never use `1px solid` borders. Use background shifts, spacing, or tonal transitions.
- **Tonal Layering:** Depth via background colors: Level 0 `#f8f9fa`, Level 1 `#f1f4f6`, Level 2 `#ffffff`
- **Ghost Borders:** `outline-variant` at 15% opacity when borders are needed
- **Sentence case:** All labels, headers, buttons. No Title Case or ALL CAPS.
- **Text color:** Never use pure `#000000`. Use `on-surface` (`#2b3437`).

## Repository Layout

```
backend/              FastAPI app (Python)
  cliff/
    main.py           App entry point, lifespan, CORS
    config.py         Settings via env vars
    engine/           OpenCode integration (process manager, HTTP client, process pool)
    agents/           Agent template engine (Jinja2 templates for 6 agents)
    workspace/        Workspace runtime (directory manager, context builder, agent run log)
    api/routes/       REST endpoints (health, sessions, chat, workspace-scoped chat)
frontend/             React SPA (TypeScript + Vite + Tailwind)
  src/
    pages/            Page components (Findings, Workspace, History, Integrations, Settings)
    api/              API client + TanStack Query hooks
    components/       Shared components (layout, Markdown, ResultCard)
    layouts/          App layout (SideNav + TopBar + Outlet)
    lib/              Utilities (cn(), query-client)
  mockups/            Stitch HTML + screenshots (design reference)
  tailwind.config.ts  Full Stitch color tokens
docker/               Dockerfile, docker-compose, supervisord config
docs/
  adr/                Architecture Decision Records
  architecture/       System diagrams, domain model, adapter specs, agent pipeline
  guides/             Developer setup, Docker build, adding adapters
scripts/              dev.sh, install-opencode.sh
fixtures/             Mock/demo data for adapters
tests/                Cross-stack integration tests
.opencode/agents/     Custom OpenCode agent definitions
.opencode-version     Pinned OpenCode version
opencode.json         OpenCode project config
```

## Key Domain Concepts

- **Finding** — A vulnerability from a scanner. Flows through: `new` -> `triaged` -> `in_progress` -> `remediated` -> `validated` -> `closed`
- **Workspace** — A remediation session for one Finding. Each workspace gets an isolated directory (`data/workspaces/<id>/`) with finding-specific context, rendered agent templates, and its own OpenCode process
- **AgentRun** — A single sub-agent execution (enricher, owner resolver, planner, etc.)
- **SidebarState** — Persistent structured context per workspace (summary, evidence, owner, plan, ticket, validation)
- **Adapter** — Interface to an external system. Four types: FindingSource, OwnershipContext, Ticketing, Validation

See `docs/architecture/domain-model.md` for entity details and state machines.

## Pages

| Page | Purpose |
|------|---------|
| Findings | List, filter, sort, and import findings. "Solve" opens a Workspace |
| Workspace | Chat-led remediation with sidebar, agent cards, and actions |
| History | Browse completed workspaces, replay chats |
| Integrations | Configure adapter connections |
| Settings | Model/provider config, agent settings |

## Sub-Agents

1. **Finding Enricher** — CVE details, severity, exploit info -> updates `summary`, `evidence`
2. **Owner Resolver** — Team/person identification with evidence -> updates `owner`
3. **Exposure/Context Analyzer** — Reachability, environment, criticality -> updates `evidence`
4. **Remediation Planner** — Fix plan, mitigations, definition of done -> updates `plan`
5. **Validation Checker** — Confirms fix, recommends close/reopen -> updates `validation`

See `docs/architecture/agent-pipeline.md` for I/O contracts.

## Build & Development

### Prerequisites

- Python 3.11+ with uv
- Node.js 20+ with npm
- Docker (for containerized runs)

### Commands

```bash
# Full dev environment (backend + frontend)
scripts/dev.sh

# Backend only
cd backend && uv run uvicorn cliff.main:app --reload --port 8000

# Frontend only (needs backend running for API proxy)
cd frontend && npm run dev

# Install OpenCode binary (auto-downloads pinned version)
scripts/install-opencode.sh

# Tests
cd backend && uv run pytest
cd frontend && npm test
```

### How It Runs

1. FastAPI starts on port 8000 and launches a singleton OpenCode process on port 4096 (for health/settings)
2. When a user opens a workspace, a **per-workspace OpenCode process** starts on a port from range 4100-4199, with `cwd=data/workspaces/<id>/` (isolated context)
3. Vite dev server starts on port 5173 and proxies `/api/*` to FastAPI
4. Browser talks to Vite (5173) in dev, or FastAPI (8000) in production
5. All OpenCode communication goes through FastAPI — frontend never talks to OpenCode directly
6. Idle workspace processes are automatically stopped after 10 minutes (configurable via `CLIFF_WORKSPACE_IDLE_TIMEOUT_SECONDS`)

## Testing

Every phase must have tests passing before it is considered complete.

```bash
# Unit tests only (fast, no external deps)
cd backend && uv run pytest -v -m 'not e2e'

# E2E tests (needs OpenCode binary + OPENAI_API_KEY)
cd backend && uv run pytest tests/e2e/ -v

# All tests
cd backend && uv run pytest -v

# Lint
cd backend && uv run ruff check cliff/ tests/
```

### Unit tests (187, ~0.9s)

Mocked external dependencies — no real OpenCode needed:

- `test_config.py` — Settings and path resolution
- `test_models.py` — Pydantic model validation
- `test_engine_client.py` — OpenCode HTTP client (mocked httpx)
- `test_engine_process.py` — Subprocess lifecycle
- `test_routes_*.py` — API endpoint behavior with mocked engine
- `test_workspace_dir.py` — Workspace directory manager (Layer 0, 29 tests)
- `test_agent_template_engine.py` — Agent template rendering (Layer 1, 18 tests)
- `test_context_builder.py` — Context builder orchestration (Layer 2, 13 tests)
- `test_process_pool.py` — Process pool with mocked subprocess (Layer 3, 15 tests)

### E2E tests (25, ~50s)

Real OpenCode subprocess + real LLM calls. Skipped automatically if OpenCode binary or API key is missing:

- `e2e/test_health_e2e.py` — Health with real engine
- `e2e/test_session_flow.py` — Session create/list/get
- `e2e/test_chat_flow.py` — Send message, verify round-trip
- `e2e/test_error_handling.py` — Error cases
- `e2e/test_settings_e2e.py` — Model/provider/API key management
- `e2e/test_process_pool_e2e.py` — Real per-workspace OpenCode processes (10 tests: concurrent workspaces, port exhaustion, crash recovery, idle cleanup)

## Git Workflow

**Direct pushes to `main` are not allowed.** All changes must go through a pull request reviewed and merged by `@galanko`.

When working on any task, follow this workflow:

1. **Create a feature branch** from `main` with a descriptive name (e.g. `feat/add-adapter-api`, `fix/session-timeout`)
2. **Make changes and commit** using conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
3. **Push the branch** to the remote (`git push -u origin <branch-name>`)
4. **Create a pull request** targeting `main`. Include a summary of changes and a test plan
5. **Wait for approval** — `@galanko` is the required code owner and must review and merge the PR. Do NOT merge pull requests yourself

Never commit directly to `main`. Never force-push to `main`. If tests or lint fail, fix them before requesting review.

## Development Conventions

- **ADRs:** Every architectural decision gets a record in `docs/adr/`. Use the template in `docs/adr/README.md`
- **Adapters:** Mock-first. Real integrations implement the same interface. See `docs/architecture/adapter-interfaces.md`
- **Agent output rule:** Every agent result must persist into both the chat timeline AND the SidebarState. Never only chat
- **Commits:** Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- **Python style:** ruff for linting/formatting, strict type hints, Pydantic models
- **TypeScript style:** ESLint + Prettier, strict mode
- **Interaction grammar:** Every user action follows `ask -> run -> summarize -> persist -> decide next`

## Workspace Runtime Architecture (ADR-0014)

Each workspace gets an isolated environment. See `docs/adr/0014-workspace-runtime-architecture.md`.

| Layer | Component | Status |
|-------|-----------|--------|
| 0 | `WorkspaceDirManager` — filesystem CRUD, CONTEXT.md generation | Complete |
| 1 | `AgentTemplateEngine` — Jinja2 templates for 6 agents | Complete |
| 2 | `WorkspaceContextBuilder` — orchestrates L0 + L1 + DB metadata | Complete |
| 3 | `WorkspaceProcessPool` — per-workspace OpenCode processes | Complete |
| 4 | API integration — workspace-scoped sessions, chat, context routes | Complete |

Key files: `backend/cliff/workspace/`, `backend/cliff/engine/pool.py`, `backend/cliff/agents/`

## AI provider integration (ADR-0037, supersedes ADR-0036)

Cliff's AI provider key flows into per-workspace OpenCode subprocesses
via env vars at spawn time, plus a parallel push to OpenCode's `auth.json`
(both paths because OpenCode 1.3.x prefers `auth.json` on the outbound
request). Six supported providers: OpenRouter, Anthropic, OpenAI, Google,
Ollama, custom OpenAI-compatible.

**One canonical state, derived everywhere else.** Provider + key live in
`ai_integration` + `credential` vault entry. Active model is
`app_setting(key="model")`. Per-workspace `opencode.json` and the
singleton `opencode.json` are reconciled from these two at every save +
spawn. `CLIFF_AI_MODEL_OVERRIDE_*` env vars are a DEV/CI escape hatch
only — the UI picker is the canonical write path.

**Three onboarding tiers (ADR-0035):**

- **Tier 1**: auto-detect existing keys (`~/.claude/.credentials.json`,
  `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`/`OPENAI_API_KEY` env vars,
  `~/.aider/.env`, `~/.config/openai/`).
- **Tier 2**: OpenRouter OAuth PKCE — backend runs the handshake on
  `localhost:3000`. Two clicks.
- **Tier 3**: direct BYOK with deep-linked provider instructions
  (Anthropic, OpenAI, Google AI Studio, Local Ollama, Custom).

**Defaults per provider:** OpenRouter → `tencent/hy3-preview`; Anthropic →
`claude-haiku-4-5`; OpenAI → `gpt-5`; Google → `gemini-2.5-flash`;
Ollama → user-picked from `/api/tags`. Users override via the picker in
Settings.

**Drift detection.** `GET /api/integrations/ai/status` returns both the
canonical model and a live probe of OpenCode's `/config`. When they
disagree the Settings card shows a red banner with a one-click reconcile,
and `cliff status` reports `drifted: true` with both values.

Key files: `backend/cliff/ai/`, `backend/cliff/api/routes/ai_integrations.py`,
`frontend/src/components/ai-provider/`. User-facing guide:
`docs/guides/setup-ai-provider.md`.

## Development Workflow

Cliff uses a 4-team pipeline with CEO approval gates. Each team is a Claude Code skill.

### Teams

| Team | Skill | Purpose |
|------|-------|---------|
| Product | `/product-manager` | PRDs, user stories, roadmap updates |
| UI/UX | `/ux-designer` | Mockups (via Stitch MCP), UX specs, design system enforcement |
| Architect | `/architect` | ADRs, implementation plans, plan review, post-mortems |
| R&D: App Builder | `/app-builder` | Frontend, integrations, API, Docker (Vertical 2) |
| R&D: Agent Orchestrator | `/cliff-agent-orchestrator` | Agent pipeline, workspace runtime, engine (Vertical 1) |

### Pipeline

Use `/pipeline "<feature description>"` to run the full flow autonomously:

1. **Product** drafts PRD → CEO approves
2. **UX** creates mockups + spec → CEO approves
3. **Architect** writes ADR + implementation plan → CEO approves
4. **R&D** implements with TDD, creates PR → CEO merges

Each gate pauses for CEO review. After approval, the next team starts automatically.

Individual skills can also be invoked directly (e.g., `/product-manager` for a standalone PRD).

### Where things live

| What | Where |
|------|-------|
| PRDs | `docs/product/prds/PRD-XXXX-slug.md` |
| PRD template | `docs/product/templates/prd-template.md` |
| UX specs | `docs/design/specs/UX-XXXX-slug.md` |
| UX language guide | `docs/design/ux-language.md` |
| Implementation plans | `docs/architecture/plans/IMPL-XXXX-slug.md` |
| ADRs | `docs/adr/NNNN-slug.md` |
| Task tracking | Notion (primary) + `docs/BACKLOG.md` (agent-readable mirror) |

### Quality gates

| Stage | Enforced by |
|-------|------------|
| PRD completeness | `/product-manager` follows template + CEO review |
| Design system compliance | `/ux-designer` enforces Serene Sentinel rules |
| Architectural simplicity | `/architect` review + `/brainstorming` before ADRs |
| Code quality | TDD-first, `/simplify`, CI lint+test, 3-strike safeguard |
| Final review | CEO reviews + merges PR on GitHub |

## Current Phase

See `ROADMAP.md` — **Stages 1 and 2** complete. Currently in **Stage 3** (Phase 6b: Agent Orchestration — wiring agents into the isolated workspace runtime).
