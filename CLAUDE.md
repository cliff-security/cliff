# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Cliff is a self-hosted cybersecurity remediation copilot. It ingests vulnerability findings, enriches them with AI agents, and guides users through planning, ticketing, validating, and closing remediations — all from a chat-led web workspace.

Agents run in-process on [Pydantic AI](https://ai.pydantic.dev/) (ADR-0047). Single-user community edition. AGPL-3.0 licensed.

> **Historical names — Cliff was called OpenSec, then briefly at `galanko/cliff`.** Until May 2026 this project was named "OpenSec" and lived at `github.com/galanko/OpenSec`. It was renamed to Cliff (briefly at `github.com/galanko/cliff`) and then transferred to a dedicated org at `github.com/cliff-security/cliff` in May 2026 (GitHub redirects from both old URLs). Any mention of "OpenSec", `galanko/OpenSec`, or `galanko/cliff` you encounter — in commit history, old branch names like `chore/cliff-os-restructure` referencing OpenSec snapshots, archived ADRs, third-party content, environment variables prefixed `OPENSEC_*`, Python modules named `opensec.*`, or the `cliff-os` private umbrella's pre-rename docs — refers to this same project. Treat all three as the same thing; the renames were cosmetic and organizational.

## Where to find architecture context

This repo is the public app code only. Architecture decisions (ADRs), system diagrams, implementation plans, product specs (PRDs), design specs, QA evidence, and strategy memos live in the **private `cliff-os` umbrella repo** alongside this one (typically cloned as a sibling at `~/projects/cliff-os/`, with the public `cliff` repo at `~/projects/cliff-os/cliff/` or `~/projects/OpenSec/`).

When working on this codebase:

- Before any non-trivial architectural change, read the relevant ADRs and architecture docs in the private `cliff-os/docs/` tree.
- When you change behavior that an ADR or IMPL plan documents, update that doc in the same change (in `cliff-os`, not here).
- If you can't access the private docs, ask the maintainer rather than making the call without them.
- The `docs/assets/` directory in this repo is **mirrored** from `cliff-os/docs/assets/` — see [`docs/assets/README.md`](docs/assets/README.md) for the sync rule.

## Architecture

| Layer | Technology | Location |
|-------|-----------|----------|
| Frontend | React + TypeScript + Vite + Tailwind | `frontend/` |
| Backend | FastAPI (Python 3.11+) | `backend/` |
| AI substrate | Pydantic AI — agents run in-process (ADR-0047) | `backend/cliff/agents/runtime/` |
| Workspace Runtime | Per-workspace isolated context directory (ADR-0014) | `backend/cliff/workspace/` |
| Database | SQLite (single file) | `data/cliff.db` |
| Deployment | Single Docker container, port 8000 | `docker/` |

See `cliff-os/docs/architecture/overview.md` (private) for the full system diagram, `cliff-os/docs/adr/0047-pydantic-ai-substrate.md` (private) for the substrate, and `cliff-os/docs/adr/0014-workspace-runtime-architecture.md` (private) for the workspace isolation architecture.

## Design System: "Cyberdeck"

The UI follows the Cyberdeck design system shipped at v0.2.0 — dark-navy operator console with a single sage-mint accent, almost-square geometry, mono labels, barely-visible scanline texture. **Dark mode is the default and the only mode.** The earlier "Serene Sentinel" / "Granite" light-mode identity is deprecated.

Canonical brand reference: **`cliff-os/gtm/DESIGN.md`** (private). The CSS tokens at `frontend/src/styles/cyberdeck.css` are the load-bearing source for the app; if a value here disagrees with that file, the CSS wins.

| Aspect | Choice |
|--------|--------|
| Creative direction | Operator console — calm, terminal-like, intentional |
| Color mode | Dark default (only mode) |
| Primary accent | sage-mint (`var(--cd-green)`) |
| Background | dark navy (`var(--cd-bg)`, `var(--cd-bg-1)`) — see `cyberdeck.css` |
| Headlines font | font-display (Cabinet Grotesk, weights 700–800) |
| Body/labels font | Inter (400–600) |
| Mono / labels | JetBrains Mono — used for all eyebrows, codes, IDs |
| Icons | Google Material Symbols Outlined |
| Color tokens | See `frontend/src/styles/cyberdeck.css` and `frontend/tailwind.config.ts` |

**Core design rules:**
- **No-Line Rule:** Avoid `1px solid` borders. Use background shifts, spacing, or tonal transitions. Subtle 1px CSS-variable rules (`var(--cd-rule)`) are acceptable as ghost borders.
- **Tonal Layering:** Depth via dark-mode background tiers (`--cd-bg`, `--cd-bg-1`, `--cd-bg-2`).
- **Sentence case:** All labels, headers, buttons in sentence case. **Exception:** small-caps mono eyebrows (tracking-wide, ≤11px, used as category tags above primary headings — e.g. "STEP 1 OF 3", "RECOMMENDED"). The eyebrow exception is intentional Cyberdeck typography. Anything larger than a micro-label or that acts as body/hero copy must be sentence case.
- **Text color:** Never pure `#000000` or pure `#ffffff`. Use the Cyberdeck `--cd-fg-*` tiers.

## Repository Layout

```
backend/              FastAPI app (Python)
  cliff/
    main.py           App entry point, lifespan, CORS
    config.py         Settings via env vars
    agents/           Agent definitions + orchestration
      runtime/        Pydantic AI agents, tools, provider factory (ADR-0047)
    workspace/        Workspace runtime (directory manager, context builder, agent run log)
    api/routes/       REST endpoints (health, findings, workspace, posture, …)
frontend/             React SPA (TypeScript + Vite + Tailwind)
  src/
    pages/            Page components (Issues, Workspace, Integrations, Settings)
    api/              API client + TanStack Query hooks
    components/       Shared components (layout, Markdown, ResultCard)
    layouts/          App layout (SideNav + TopBar + Outlet)
    lib/              Utilities (cn(), query-client)
  mockups/            Stitch HTML + screenshots (design reference)
  tailwind.config.ts  Full Stitch color tokens
docker/               Dockerfile, docker-compose, supervisord config
docs/
  assets/             Public images: wordmark, badge, demo gif, screenshots
                      (mirrored from cliff-os/docs/assets/ — see README there)
scripts/              dev.sh, install-scanners.sh
fixtures/             Mock/demo data for adapters
tests/                Cross-stack integration tests
```

## Key Domain Concepts

- **Finding** — A vulnerability from a scanner. Flows through: `new` -> `triaged` -> `in_progress` -> `remediated` -> `validated` -> `closed`
- **Workspace** — A remediation session for one Finding. Each workspace gets an isolated directory (`data/workspaces/<id>/`) with finding-specific context the in-process Pydantic AI agents read at run time
- **AgentRun** — A single sub-agent execution (enricher, owner resolver, planner, etc.)
- **SidebarState** — Persistent structured context per workspace (summary, evidence, owner, plan, ticket, validation)
- **Adapter** — Interface to an external system. Four types: FindingSource, OwnershipContext, Ticketing, Validation

See `cliff-os/docs/architecture/domain-model.md` (private) for entity details and state machines.

## Pages

| Page | Purpose |
|------|---------|
| Findings | List, filter, sort, and import findings. "Solve" opens a Workspace |
| Workspace | Chat-led remediation with sidebar, agent cards, and actions |
| Integrations | Configure adapter connections |
| Settings | Model/provider config, agent settings |

## Sub-Agents

1. **Finding Enricher** — CVE details, severity, exploit info -> updates `summary`, `evidence`
2. **Owner Resolver** — Team/person identification with evidence -> updates `owner`
3. **Exposure/Context Analyzer** — Reachability, environment, criticality -> updates `evidence`
4. **Remediation Planner** — Fix plan, mitigations, definition of done -> updates `plan`
5. **Validation Checker** — Confirms fix, recommends close/reopen -> updates `validation`

See `cliff-os/docs/architecture/agent-pipeline.md` (private) for I/O contracts.

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

# Tests
cd backend && uv run pytest
cd frontend && npm test
```

### How It Runs

1. FastAPI starts on port 8000. There is no agent subprocess — agents run **in-process** via Pydantic AI (ADR-0047)
2. When a user opens a workspace, an isolated context directory is created at `data/workspaces/<id>/` (finding context + per-agent context sections the agents read at run time)
3. Each agent run builds a fresh Pydantic AI `Model` from the canonical AI provider state (`backend/cliff/agents/runtime/provider.py`) and calls `agent.run()` in-process
4. Vite dev server starts on port 5173 and proxies `/api/*` to FastAPI; browser talks to Vite (5173) in dev, or FastAPI (8000) in production

## Testing

Every phase must have tests passing before it is considered complete.

```bash
# Backend unit tests (fast, no external deps — agents use FunctionModel/TestModel)
cd backend && uv run pytest -v -m 'not e2e'

# Lint
cd backend && uv run ruff check cliff/ tests/

# Frontend
cd frontend && npm test && npx tsc --noEmit
```

Backend agent tests drive the Pydantic AI runtime with `FunctionModel` /
`TestModel`, so no real LLM or network is needed — except the live eval
(`tests/agents/test_plain_description_eval.py`), which is skipped unless an
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` is set.

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

- **ADRs:** Every architectural decision gets a record in `cliff-os/docs/adr/` (private). Use the template in `cliff-os/docs/adr/README.md`.
- **Adapters:** Mock-first. Real integrations implement the same interface. See `cliff-os/docs/architecture/adapter-interfaces.md` (private).
- **Agent output rule:** Every agent result must persist into both the chat timeline AND the SidebarState. Never only chat
- **Commits:** Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- **Python style:** ruff for linting/formatting, strict type hints, Pydantic models
- **TypeScript style:** ESLint + Prettier, strict mode
- **Interaction grammar:** Every user action follows `ask -> run -> summarize -> persist -> decide next`

## Workspace Runtime Architecture (ADR-0014)

Each workspace gets an isolated environment. See `cliff-os/docs/adr/0014-workspace-runtime-architecture.md` (private).

| Layer | Component | Status |
|-------|-----------|--------|
| 0 | `WorkspaceDirManager` — filesystem CRUD, CONTEXT.md generation | Complete |
| 1 | `WorkspaceContextBuilder` — orchestrates the dir + finding context + DB metadata | Complete |
| 2 | Pydantic AI runtime (`agents/runtime/`) — in-process agents + tools (ADR-0047) | Complete |
| 3 | API integration — workspace-scoped agent-run + context routes | Complete |

Key files: `backend/cliff/workspace/`, `backend/cliff/agents/runtime/`, `backend/cliff/agents/executor.py`

## AI provider integration (ADR-0037, supersedes ADR-0036)

Cliff's AI provider key is resolved at each agent run into the env the
Pydantic AI model factory (`agents/runtime/provider.py`) reads (ADR-0047).
Six supported providers: OpenRouter, Anthropic, OpenAI, Google, Ollama,
custom OpenAI-compatible.

**One canonical state, derived everywhere else.** Provider + key live in
`ai_integration` + `credential` vault entry. Active model is
`app_setting(key="model")`. The lifespan warms an env + model cache from
these and refreshes it on every connect / disconnect / model change.
`CLIFF_AI_MODEL_OVERRIDE_*` env vars are a DEV/CI escape hatch only — the
UI picker is the canonical write path.

**Three onboarding tiers (ADR-0035):**

- **Tier 1**: auto-detect existing keys (`~/.claude/.credentials.json`,
  `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`/`OPENAI_API_KEY` env vars,
  `~/.aider/.env`, `~/.config/openai/`).
- **Tier 2**: OpenRouter OAuth PKCE — backend runs the handshake on
  `localhost:3000`. Two clicks.
- **Tier 3**: direct BYOK with deep-linked provider instructions
  (Anthropic, OpenAI, Google AI Studio, Local Ollama, Custom).

**Defaults per provider:** OpenRouter → `anthropic/claude-haiku-4.5`;
Anthropic → `claude-haiku-4-5`; OpenAI → `gpt-5`; Google →
`gemini-2.5-flash`; Ollama → user-picked from `/api/tags`. Users
override via the picker in Settings. (Previously the OpenRouter default
was `tencent/hy3-preview`; that was a single-upstream-provider model and
broke under concurrent agent runs, so it was demoted to a picker option.)

**No drift signal.** With the substrate in-process there is no separate
engine config to drift from — `GET /api/integrations/ai/status` returns
the single canonical model. (The earlier live-probe-vs-canonical drift
banner was an OpenCode-era concern.)

Key files: `backend/cliff/ai/`, `backend/cliff/api/routes/ai_integrations.py`,
`frontend/src/components/ai-provider/`. User-facing guide:
`cliff-os/docs/guides/setup-ai-provider.md` (private).

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

All knowledge-base artifacts (PRDs, UX specs, IMPL plans, ADRs, BACKLOG) live in the **private `cliff-os` umbrella** — not in this public repo.

| What | Where (in `cliff-os/`) |
|------|------------------------|
| PRDs | `docs/product/prds/PRD-XXXX-slug.md` |
| PRD template | `docs/product/templates/prd-template.md` |
| UX specs | `docs/design/specs/UX-XXXX-slug.md` |
| UX language guide | `docs/design/ux-language.md` |
| Implementation plans | `docs/architecture/plans/IMPL-XXXX-slug.md` |
| ADRs | `docs/adr/NNNN-slug.md` |
| Task tracking | Notion (primary) + `cliff-os/docs/BACKLOG.md` (agent-readable mirror) |

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
