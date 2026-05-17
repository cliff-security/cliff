# ADR-0014: Workspace Runtime Architecture — Isolated Context Environments

**Date:** 2026-03-27
**Status:** Proposed
**Supersedes:** Portions of ADR-0001 (single OpenCode process), ADR-0008 (agent execution model)

## Context

Cliff's value proposition is not "chat with an LLM about security." It's "an AI copilot that already understands your specific vulnerability, your environment, your code, and your team — before you type a word."

Today, OpenCode runs as a single process against the repository root. All workspaces share the same context, same agents, same config. A workspace is just a database row. This is fundamentally wrong for what we're building.

### The problem in concrete terms

1. **No context isolation.** If a user opens Workspace A for a Log4j CVE and Workspace B for an expired TLS cert, both sessions see the same files, same agents, same system prompt. The AI has no pre-loaded knowledge about either finding.

2. **No context assembly.** The finding enricher, owner resolver, and exposure analyzer all produce structured output — but none of it becomes part of the AI's working context. It lives in the database, not in the agent's brain.

3. **No workspace persistence on disk.** When a workspace is "resumed," there's no filesystem state to restore. The AI starts cold every time.

4. **Shared process = shared failure.** One bad session can affect all others. One model config change applies everywhere. No ability to run different models per workspace.

### What we're actually building

Claude Code works because each project has its own directory, its own `CLAUDE.md`, its own context. When you open a project, Claude already knows what it is, how it's structured, what the conventions are.

We're building the same thing for security remediation. Each workspace is a **project directory** that contains everything the AI needs to be an expert on that specific vulnerability:

- The finding details, pre-loaded
- The enrichment data from prior agent runs
- The ownership and exposure context
- The remediation plan in progress
- Agent definitions tuned for this finding type
- Guidelines specific to this vulnerability class

The context is the product. The context assembly is our art.

---

## Decision

### 1. Each workspace gets an isolated directory on disk

```
data/workspaces/<workspace-id>/
  opencode.json              # Workspace-specific OpenCode config
  CONTEXT.md                 # Auto-generated context document (the "brain")
  .opencode/
    agents/
      orchestrator.md        # Workspace orchestrator (finding-aware)
      enricher.md            # Finding enricher (customized per vuln type)
      owner-resolver.md      # Owner resolver
      exposure-analyzer.md   # Exposure analyzer
      remediation-planner.md # Remediation planner
      validation-checker.md  # Validation checker
  context/
    finding.json             # Raw finding payload
    finding.md               # Human-readable finding summary
    enrichment.json          # Enrichment results (grows over time)
    ownership.json           # Ownership resolution results
    exposure.json            # Exposure analysis results
    plan.json                # Remediation plan
    validation.json          # Validation results
    code-snippets/           # Relevant code fragments (if applicable)
    references/              # CVE advisories, KB articles, etc.
  history/
    agent-runs.jsonl         # Append-only log of all agent executions
```

**Why a directory, not just database rows?**
- OpenCode uses the `cwd` to determine its working context. Files in the directory ARE the agent's knowledge.
- `CONTEXT.md` is the equivalent of `CLAUDE.md` — it tells the orchestrator everything it needs to know.
- Agent prompts can reference `context/` files directly — "read the finding details in context/finding.md."
- The directory IS the workspace state. Back it up, move it, replay it.
- Contributors can inspect and debug workspace state by looking at files, not querying a database.

### 2. Context Builder — the engine that assembles knowledge

A new `WorkspaceContextBuilder` assembles the workspace directory when a workspace is created, and updates it as new information arrives.

```
WorkspaceContextBuilder
  ├── create(finding: Finding) -> workspace_dir
  │     Creates directory structure
  │     Writes finding.json and finding.md
  │     Generates CONTEXT.md with finding summary
  │     Copies and customizes agent definitions
  │     Writes opencode.json with workspace config
  │
  ├── update_context(workspace_id, section, data)
  │     Updates context/*.json files after agent runs
  │     Regenerates CONTEXT.md with new knowledge
  │     Updates agent prompts if context changes what they need
  │
  ├── get_context_snapshot(workspace_id) -> dict
  │     Returns current state of all context files
  │     Used by the API to show sidebar state
  │
  └── archive(workspace_id)
        Compresses workspace dir for history
        Keeps metadata in DB for search
```

**CONTEXT.md generation** is the key operation. This file is what the orchestrator agent reads first. It's auto-generated from structured data:

```markdown
# Workspace Context

## Finding
- **Title:** Remote Code Execution in log4j (CVE-2021-44228)
- **Severity:** Critical (CVSS 10.0)
- **Asset:** api-gateway (prod)
- **Status:** in_progress

## What we know so far
[Auto-generated from enrichment, ownership, exposure data]

## Current plan
[Auto-generated from remediation planner output, if exists]

## What needs to happen next
[Auto-generated based on which agents have run and what's missing]

## Files in this workspace
- `context/finding.json` — Raw finding payload from scanner
- `context/enrichment.json` — CVE details, exploit info, affected versions
- [... more as they're created]
```

### 3. OpenCode process management — per-workspace instances

**Decision:** Run a **separate OpenCode process per active workspace**, managed by a process pool.

```
WorkspaceProcessPool
  ├── start(workspace_id) -> OpenCodeClient
  │     Starts OpenCode with cwd=workspace_dir
  │     Assigns a unique port from the port range
  │     Returns a client bound to that instance
  │
  ├── get(workspace_id) -> OpenCodeClient | None
  │     Returns client for running workspace, or None
  │
  ├── stop(workspace_id)
  │     Gracefully stops the workspace's OpenCode process
  │
  ├── stop_idle(max_idle: timedelta)
  │     Stops processes that haven't received a message in max_idle
  │     Frees ports and memory
  │
  └── status() -> dict
        Lists active processes, ports, memory usage
```

**Port allocation:** Range `4100-4199` (100 concurrent workspaces max). Port = `4100 + (workspace_index % 100)`. Tracked in a port registry.

**Lifecycle:**
1. User opens workspace -> process starts (or reattaches if already running)
2. User sends message -> routed to workspace's OpenCode instance
3. User navigates away -> idle timer starts (default: 10 minutes)
4. Idle timeout -> process stopped, port freed
5. User returns -> process restarts, session restored from workspace directory

**Why per-workspace processes, not a shared process?**
- True `cwd` isolation — each process sees only its workspace files
- Independent model configuration per workspace
- One crash doesn't affect other workspaces
- Can run different OpenCode versions per workspace (future)
- Memory is bounded — idle workspaces cost zero resources

**Why not containers (Docker-in-Docker)?**
- Massive complexity for MVP, diminishing returns for single-user
- OpenCode processes are lightweight (~30MB each)
- Filesystem isolation via `cwd` is sufficient for the threat model
- Container isolation is a future enterprise feature

### 4. Agent definitions — templated, finding-aware

Agent definitions are **templates** that get rendered with finding context when the workspace is created.

Base templates live in the repository:

```
backend/cliff/agents/templates/
  orchestrator.md.j2
  enricher.md.j2
  owner-resolver.md.j2
  exposure-analyzer.md.j2
  remediation-planner.md.j2
  validation-checker.md.j2
```

When a workspace is created, the context builder renders these templates with the finding data and writes the results to the workspace's `.opencode/agents/` directory.

Example template (`orchestrator.md.j2`):

```markdown
---
description: Security remediation orchestrator for {{ finding.title }}
mode: primary
---

You are a cybersecurity remediation copilot working on a specific vulnerability.

## Your current finding

- **Title:** {{ finding.title }}
- **CVE:** {{ finding.cve_ids | join(', ') if finding.cve_ids else 'Not yet identified' }}
- **Severity:** {{ finding.raw_severity | upper }}
- **Asset:** {{ finding.asset_label }} ({{ finding.asset_id }})
- **Status:** {{ finding.status }}

{% if enrichment %}
## What we know
{{ enrichment.summary }}
{% endif %}

{% if owner %}
## Owner
{{ owner.recommended_owner }} ({{ owner.confidence }}% confidence)
{% endif %}

## Your workspace files
Read `CONTEXT.md` for the full picture. Detailed data is in the `context/` directory.

## Your responsibilities
[... same as current orchestrator, but now context-aware ...]

## Available sub-agents
You can delegate to these specialists:
- **enricher** — Enrich the finding with CVE details, exploit info, affected versions
- **owner-resolver** — Identify the responsible team with evidence
- **exposure-analyzer** — Assess reachability and blast radius
- **remediation-planner** — Generate fix plan with steps and definition of done
- **validation-checker** — Confirm the fix resolved the vulnerability

## Interaction pattern
ask -> run -> summarize -> persist -> decide next

After each agent run, update CONTEXT.md and the relevant context/*.json file.
```

**Why templates, not static files?**
- The orchestrator needs to know the finding details from the start
- Different finding types need different emphasis (a code vuln vs a misconfiguration vs an expired cert)
- Templates are testable — unit test the rendered output
- Contributors can modify templates without touching Python code

### 5. Context update pipeline — keeping the brain current

After every agent run, the context builder updates the workspace:

```
Agent completes
  → FastAPI receives structured_output
  → Persists to DB (AgentRun, SidebarState) — unchanged
  → Calls context_builder.update_context(workspace_id, agent_type, output)
      → Writes output to context/<agent_type>.json
      → Regenerates CONTEXT.md with all current knowledge
      → Optionally re-renders agent templates if context changes affect them
  → Returns result to chat
```

This means the AI's context file always reflects the latest state. If the enricher discovers it's a critical RCE with a public exploit, the orchestrator's CONTEXT.md will say so — and the planner agent will see it too.

### 6. Database changes

Add to the `workspace` table:

```sql
ALTER TABLE workspace ADD COLUMN workspace_dir TEXT;        -- Filesystem path
ALTER TABLE workspace ADD COLUMN opencode_session_id TEXT;   -- Current OpenCode session
ALTER TABLE workspace ADD COLUMN opencode_port INTEGER;      -- Port if process is running
ALTER TABLE workspace ADD COLUMN context_version INTEGER DEFAULT 0; -- Context rebuild counter
```

The DB remains the source of truth for metadata and search. The filesystem is the source of truth for AI context.

### 7. Workspace lifecycle

```
          create_workspace(finding)
                 │
                 ▼
         ┌──────────────┐
         │  INITIALIZING │  Context builder assembling directory
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐
         │    READY      │  Directory built, no process running
         └──────┬───────┘
                │  user opens workspace
                ▼
         ┌──────────────┐
         │   ACTIVE      │  OpenCode process running, chat enabled
         └──────┬───────┘
                │  idle timeout / user navigates away
                ▼
         ┌──────────────┐
         │  SUSPENDED    │  Process stopped, directory preserved
         └──────┬───────┘
                │  user returns
                ▼
         ┌──────────────┐
         │   ACTIVE      │  Process restarted, context reloaded
         └──────────────┘
                │  workspace closed
                ▼
         ┌──────────────┐
         │  ARCHIVED     │  Directory compressed, metadata in DB
         └──────────────┘
```

---

## Options Considered and Rejected

### Option A: Shared OpenCode process with context injection via system prompts

**Approach:** Keep one OpenCode process. Inject finding context via the system message at session creation time.

**Why rejected:**
- OpenCode's `cwd` determines what files agents can see. A shared process sees the repo, not workspace-specific files.
- No filesystem isolation — agents can't be told "read the finding from context/finding.json" because those files don't exist in a shared directory.
- System prompt injection is fragile — context gets compacted away in long sessions. Files don't.
- Can't run different models per workspace.

### Option B: Docker container per workspace

**Approach:** Each workspace runs in its own Docker container with OpenCode + workspace files mounted.

**Why rejected:**
- Massive complexity for a single-user app. Docker-in-Docker or sibling containers add infrastructure burden.
- Cold start time for containers (~2-5s) vs processes (~0.5s).
- Port management, networking, and volume mounting add failure modes.
- The security boundary we need (finding isolation) doesn't require container-level isolation.
- Deferred to future enterprise edition where multi-tenant isolation matters.

### Option C: Virtual filesystem / symlink approach

**Approach:** Keep one workspace directory but use symlinks and overlayFS to create virtual views per workspace.

**Why rejected:**
- Symlinks are fragile across platforms (Windows, Docker).
- OverlayFS requires root and is Linux-only.
- Real directories are simple, debuggable, and portable.
- Disk space is cheap — a workspace directory is ~100KB.

### Option D: Database-only context (no filesystem)

**Approach:** Store all context in the database and inject it via API calls to OpenCode.

**Why rejected:**
- OpenCode is designed to work with files. Its agents read files, reference files, and understand directory structure.
- Forcing everything through API injection fights the tool instead of using it.
- Files are inspectable, diffable, and git-friendly. Database blobs are not.
- Contributors can't easily debug or modify workspace state if it's trapped in SQLite JSON columns.

---

## Implementation Plan

### Layer 0: Workspace Directory Manager (foundation)

The lowest layer. Creates, reads, updates, and deletes workspace directories. Pure filesystem operations, fully testable without OpenCode.

**Components:**
- `WorkspaceDir` — value object representing a workspace directory path
- `WorkspaceDirManager` — CRUD for workspace directories (create structure, write files, read files, archive, delete)
- `ContextDocument` — generates `CONTEXT.md` from structured data

**Tests:**
- Create workspace dir -> verify structure
- Write context file -> read it back
- Generate CONTEXT.md -> verify content
- Archive workspace -> verify compression
- Concurrent workspace creation -> verify no conflicts

### Layer 1: Agent Template Engine

Renders agent definition templates with finding context.

**Components:**
- `AgentTemplateEngine` — loads `.j2` templates, renders with context
- Base templates for all 5 sub-agents + orchestrator

**Tests:**
- Render orchestrator with full finding -> verify output
- Render with partial data (no enrichment yet) -> verify graceful handling
- Render with different finding types (CVE, misconfig, expired cert) -> verify differences

### Layer 2: Context Builder

Orchestrates directory creation + agent rendering + context updates.

**Components:**
- `WorkspaceContextBuilder` — the main orchestrator
- `ContextUpdater` — handles post-agent-run context updates

**Tests:**
- Create full workspace from finding -> verify all files
- Update context after enrichment -> verify CONTEXT.md regenerated
- Update context after each agent type -> verify correct files updated
- Idempotent updates -> same input produces same output

### Layer 3: Process Pool

Manages OpenCode processes per workspace.

**Components:**
- `WorkspaceProcessPool` — starts/stops/tracks OpenCode processes
- `PortAllocator` — manages port assignments
- `WorkspaceClient` — per-workspace OpenCode HTTP client

**Tests:**
- Start process -> verify healthy
- Stop process -> verify port freed
- Idle timeout -> verify auto-stop
- Max concurrent -> verify queuing/rejection
- Process crash -> verify cleanup

### Layer 4: API Integration

Wires everything into FastAPI routes.

**Changes:**
- `POST /workspaces` now creates directory + context
- `GET /workspaces/{id}/chat` routes to workspace-specific OpenCode
- `POST /workspaces/{id}/agent-run` triggers agent and updates context
- New: `GET /workspaces/{id}/context` returns current context state

---

## Consequences

**Positive:**
- Each workspace is a self-contained, inspectable, debuggable project
- Context quality directly improves agent quality — the AI starts smart, not blank
- Clear separation: DB for metadata/search, filesystem for AI context
- Testable at every layer — filesystem ops, template rendering, process management
- Contributors can add new agent types by adding a template file
- Workspace directories can be exported, shared, or used for training

**Negative:**
- Disk usage grows with workspaces (~100KB-1MB each, manageable)
- Process pool adds complexity vs singleton (justified by isolation benefits)
- Two sources of truth (DB + filesystem) must stay in sync
- Template rendering adds a build step to workspace creation

**Risks:**
- Port exhaustion with many concurrent workspaces. Mitigated by idle timeout and configurable range.
- Filesystem corruption could lose workspace context. Mitigated by DB being the backup source of truth — context can always be rebuilt from DB data.
- OpenCode API changes could break per-workspace process management. Mitigated by abstracting behind `WorkspaceClient`.

---

## Open Questions

1. **Should workspace directories live inside `data/` or a separate configurable path?** Leaning toward `data/workspaces/` for simplicity, with `CLIFF_WORKSPACE_DIR` env var override.

2. **How much context should go into CONTEXT.md vs individual files?** CONTEXT.md should be a summary (< 2000 tokens). Agents that need details should read from `context/*.json`.

3. **Should we version CONTEXT.md?** Git-init each workspace directory? Could enable "what changed" diffs. Probably overkill for MVP but architecturally clean.

4. **Template language:** Jinja2 (Python standard, already in FastAPI's dependency tree) vs simple string formatting. Jinja2 gives us conditionals and loops which we need for "show enrichment only if it exists."
