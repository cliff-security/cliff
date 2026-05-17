# IMPL-0001: MVP — agentic remediation

**PRD:** PRD-0001
**UX spec:** UX-0001
**ADRs:** 0014 (workspace runtime), 0021 (agent execution), 0024 (repo cloning + remediation)
**Date:** 2026-04-09
**Status:** Proposed

---

## Baseline

**What's on `main` as of 2026-04-09 (commit `0314561`):**

| Capability | Status |
|---|---|
| Findings CRUD + async chunked ingest + LLM normalizer | Complete |
| Findings page (table, filters, sort, "Solve" button) | Complete |
| Workspace lifecycle (isolated dir + process + chat SSE) | Complete |
| 5 agent templates + orchestrator (enricher, owner, exposure, planner, validator) | Complete |
| Agent executor + output parser + sidebar mapper | Complete |
| Pipeline orchestrator + suggest_next() API | Complete |
| Permission event handling (backend plumbing) | Complete |
| Workspace sidebar (summary, evidence, owner, plan, DoD, ticket, validation) | Complete |
| History page (list, filter, replay, reopen, markdown export) | Complete |
| Settings page (model, provider, API keys, integrations) | Complete |
| Integration registry + credential vault + health monitors | Complete |
| Docker (multi-stage build, supervisord, health check) | Complete |
| Database (6 migrations, 10 repo modules, SQLite WAL) | Complete |
| 187 unit tests + 25 E2E tests — all passing | Complete |

**Pending merge: `feat/permission-approval-ui`** (11 commits) — adds:
- `PermissionApprovalCard.tsx` component
- SSE listener for permission events in `WorkspacePage.tsx`
- Permission approve/deny API wiring in `api/client.ts`
- Backend: background task runner, improved executor permission flow
- Mockup refresh (simplified HTML mockups)
- Removes: bootstrap PRDs, UX audit doc, PRD template (docs cleanup)

**Assumption:** Permission-approval-ui is merged before MVP implementation begins. The plan accounts for its presence on `main`.

---

## Implementation order

The PRD defines 10 gaps (G1-G10). This plan sequences them into **7 work packages** assigned to two verticals, optimized for parallelism and dependency chains.

```
WP1: G9 Docker first-run ──────────────────── V2 (alone, unblocked)
WP2: G5 Repo access ──────────────────────── V1 (env injection) + V2 (settings UI)
WP3: G1+G2 Import UX + Onboarding ─────────── V2 (alone, parallel with WP2)
WP4: G4 Pipeline update + suggest-next ────── V1 (backend) + V2 (frontend wiring)
WP5: G6+G7 Remediation agent + PR creation ── V1 (the hero package)
WP6: G8 Status flow ──────────────────────── V1 (backend) + V2 (frontend)
WP7: G3+G10 Result cards + error handling ──── V2 (frontend, parallel with WP5/WP6)
```

**Dependency graph:**

```
                WP1 (Docker)         WP3 (Import UX)
                    │                     │
                    ▼                     ▼
WP2 (Repo clone) ──┬── WP4 (Pipeline) ──┬── WP5 (Remediation) ── WP6 (Status)
                    │                     │
                    │                WP7 (Cards + errors) ──────────┘
                    │                                               │
                    └───────────────── all converge ────────────────┘
```

**Parallel tracks:**
- V1 works WP2 → WP4 → WP5 → WP6 (sequential — each builds on prior)
- V2 works WP1, then WP3 in parallel with V1's WP2, then WP7 in parallel with V1's WP5
- WP4 and WP6 need both V1 + V2 coordination

---

## WP1: Docker first-run (G9)

**Team:** V2 (App Builder)
**Effort:** Small
**Depends on:** Nothing
**Unblocks:** Everything (clean first-run experience)

### Tasks

#### T1.1: Startup migration runner
**File:** `docker/entrypoint.sh`
**Change:** The entrypoint already calls migrations via `run_migrations()` in FastAPI lifespan. Verify it works on a fresh `data/` volume with no existing DB. Add explicit logging on first-run detection (no `cliff.db` file).
**Test:** `docker compose up` from scratch creates DB, runs all 6 migrations, app starts healthy.

#### T1.2: Seed demo mode
**File:** `backend/cliff/api/routes/seed.py` (exists), `backend/cliff/config.py`
**Change:** Add `CLIFF_DEMO` env var. When `true`, the `/seed` endpoint auto-runs on first startup (no findings in DB). Seed creates 5-10 sample findings with realistic Snyk-like data covering different severities.
**Files touched:**
- `backend/cliff/config.py` — add `demo: bool = False` field
- `backend/cliff/main.py` — call seed on lifespan if demo=True and findings table empty
- `backend/cliff/api/routes/seed.py` — verify existing seed logic covers realistic finding data
- `docker/docker-compose.yml` — add `CLIFF_DEMO=true` as commented example
**Test:** Unit test: demo flag triggers seed. Integration: `docker compose up` with `CLIFF_DEMO=true` shows populated findings page.

#### T1.3: Install `gh` CLI in Docker image
**File:** `docker/Dockerfile`
**Change:** Add `gh` CLI installation in the runtime stage. Needed for PR creation (WP5).
```dockerfile
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*
```
**Test:** `docker compose exec cliff gh --version` succeeds.

---

## WP2: Repository access (G5)

**Team:** V1 (Agent Orchestrator) + V2 (App Builder)
**Effort:** Small
**Depends on:** Nothing (can start immediately)
**Unblocks:** WP5 (remediation agent needs repo access)

**Key simplification (ADR-0024):** The agent clones the repo itself via bash — no custom Python clone code. The backend only needs to inject `GH_TOKEN` into the workspace environment and store the repo URL in settings.

### V1 task (backend)

#### T2.1: Inject GH_TOKEN into workspace OpenCode process environment
**File:** `backend/cliff/engine/pool.py`
**Change:** When starting a workspace OpenCode process, read the GitHub PAT from the credential vault and inject it as `GH_TOKEN` env var. Also read the repo URL from settings and inject as `CLIFF_REPO_URL` so the agent prompt can reference it.

**Files touched:**
- `backend/cliff/engine/pool.py` — accept `env_vars` dict, pass to subprocess
- `backend/cliff/workspace/context_builder.py` — read GitHub token + repo URL from DB, pass to pool

**Test plan:**
- Unit: verify env vars passed to subprocess
- Unit: verify token not logged or exposed in error messages
- Unit: missing token/URL → no env var injected (graceful degradation)

### V2 tasks (frontend + settings)

#### T2.5: Repository settings section in Settings page
**File:** `frontend/src/pages/SettingsPage.tsx` (or new `frontend/src/components/settings/RepoSettings.tsx`)
**Change:** Add "Repository" section with:
- GitHub repo URL input field
- Personal access token input (password field)
- "Test connection" button (calls new endpoint)
- Connection status display
- "Save" button

**New component:** `RepoSettingsSection` per UX-0001 spec.

**Files touched:**
- `frontend/src/components/settings/RepoSettings.tsx` — new component
- `frontend/src/pages/SettingsPage.tsx` — add section above AI provider
- `frontend/src/api/client.ts` — add `saveRepoSettings()`, `testRepoConnection()` API calls

**Test plan:**
- Component renders with empty state
- Displays success/error after test connection
- Persists URL + token on save

#### T2.6: Repository connection test endpoint
**File:** `backend/cliff/api/routes/settings.py`
**Change:** Add `POST /api/settings/repo/test` endpoint that:
1. Reads repo URL + token from request body
2. Runs `git ls-remote` to verify access
3. Checks if `gh` CLI works with the token (can list PRs)
4. Returns success/failure with details

**Files touched:**
- `backend/cliff/api/routes/settings.py` — new endpoint
- `backend/cliff/models.py` — add `RepoSettingsCreate`, `RepoTestResult` models

**Test plan:**
- Unit: mock subprocess, verify git ls-remote command
- Unit: mock subprocess failure → proper error response

#### T2.7: "Solve without repo" guard dialog
**File:** `frontend/src/pages/FindingsPage.tsx`
**Change:** When user clicks "Solve" but no repo is configured, show a dialog: "Repository not configured. To remediate findings, Cliff needs access to your repository." with "Configure repository" button → navigates to Settings.

**Files touched:**
- `frontend/src/pages/FindingsPage.tsx` — add guard check before workspace creation
- `frontend/src/api/client.ts` — add `getRepoSettings()` to check if configured

**Test plan:**
- Guard shows when no repo configured
- Guard doesn't show when repo configured
- "Configure repository" navigates to Settings page

---

## WP3: Import UX + Onboarding (G1 + G2)

**Team:** V2 (App Builder)
**Effort:** Medium
**Depends on:** Nothing (can run in parallel with WP2)
**Unblocks:** Dogfooding (can't test without importing real findings)

#### T3.1: ImportDialog component
**File:** `frontend/src/components/ImportDialog.tsx` — new
**Change:** Create modal dialog with two tabs:
- **Upload tab:** Drag-and-drop zone + file browser. Accepts `.json` up to 10MB.
- **Paste tab:** Textarea for pasting JSON directly.
- Both tabs call existing `POST /api/findings/ingest` endpoint.
- Progress view: wire existing `IngestProgress` component into the dialog.
- Completion view: summary (X findings imported, Y failed) with severity breakdown.

**Design:** Follow UX-0001 wireframes. Use Serene Sentinel tokens (no borders, tonal layering, sentence case).

**Test plan:**
- Dialog opens/closes
- File upload sends to ingest API
- JSON paste sends to ingest API
- Progress shows during ingest
- Completion summary renders correctly
- Error handling for invalid JSON, oversized files

#### T3.2: ImportButton in Findings toolbar
**File:** `frontend/src/pages/FindingsPage.tsx`
**Change:** Add "Import findings" button in the page toolbar (always visible, not just empty state). Uses `ActionButton` with `upload_file` icon.

#### T3.3: Empty state with import CTA
**File:** `frontend/src/pages/FindingsPage.tsx`
**Change:** When findings list is empty, show `EmptyState` with:
- Icon: `assignment_late`
- Title: "No findings yet"
- Subtitle: "Import findings from your scanner to get started."
- CTA: "Import findings" button (opens ImportDialog)
- Footer: "Supports Snyk, Wiz, and other JSON exports"

**Test plan:**
- Empty state shows when no findings
- Empty state hides when findings exist
- Import button works from empty state and from toolbar

---

## WP4: Pipeline update + suggest-next wiring (G4)

**Team:** V1 (Agent Orchestrator) + V2 (App Builder)
**Effort:** Small
**Depends on:** WP2 (pipeline includes remediation executor which needs repo)
**Unblocks:** WP5 (remediation agent needs updated pipeline)

### V1 tasks

#### T4.1: Update pipeline to 4-agent MVP sequence
**File:** `backend/cliff/agents/pipeline.py` (or wherever `suggest_next()` lives)
**Change:**
- Remove `owner_resolver` from the default pipeline sequence
- Add `remediation_executor` after `remediation_planner`
- After `remediation_executor` completes with `status=pr_created`, suggest_next returns `"review_pr"` (not another agent)
- Keep `validation_checker` available on-demand but not in the suggested pipeline

**Files touched:**
- `backend/cliff/agents/pipeline.py` or `executor.py` — update pipeline definition
- `backend/cliff/workspace/workspace_dir.py` — add `AGENT_TYPE_TO_SECTION` entry for `remediation_executor`

**Test plan:**
- Unit: suggest_next returns enricher → exposure → planner → executor sequence
- Unit: owner_resolver not suggested
- Unit: after executor with PR, suggest "review_pr"
- Unit: validation_checker still executable on-demand

#### T4.2: Update agent template engine for 4-agent pipeline
**File:** `backend/cliff/agents/template_engine.py`
**Change:** Update orchestrator template context to exclude `owner_resolver` from the default checklist. Add `remediation_executor` to the pipeline.

**Files touched:**
- `backend/cliff/agents/templates/orchestrator.md.j2` — update checklist
- `backend/cliff/agents/template_engine.py` — update template rendering context

### V2 tasks

#### T4.3: Wire suggest-next to frontend action chips
**File:** `frontend/src/components/ActionChips.tsx`
**Change:**
- Call `GET /api/workspaces/{id}/pipeline/suggest-next` to determine highlighted chip
- Remove "Find owner" chip, add "Remediate" chip
- Apply `SuggestedActionHighlight` styling to the recommended chip (per UX-0001: `bg-primary-container/30 ring-2 ring-primary/20` + subtle pulse)
- Add chip states: default, suggested, running (spinner), completed (check icon), disabled

**Files touched:**
- `frontend/src/components/ActionChips.tsx` — update chip list, add highlight logic
- `frontend/src/api/client.ts` — add `getSuggestedNext()` call (if not already wired)

**Test plan:**
- Correct chip highlighted after each agent completion
- "Find owner" chip removed
- "Remediate" chip visible after planner completes
- Disabled state when prerequisite agent hasn't run

---

## WP5: Remediation agent + PR creation (G6 + G7)

**Team:** V1 (Agent Orchestrator) — the hero work package
**Effort:** Large
**Depends on:** WP2 (repo in workspace), WP4 (pipeline includes executor)
**Unblocks:** WP6 (status flow needs PR events)

#### T5.1: Remediation executor agent template
**File:** `backend/cliff/agents/templates/remediation_executor.md.j2` — new
**Change:** Create Jinja2 template for the remediation executor. This is a tool-using agent (not pure analysis). The prompt instructs the agent to:

1. Read the remediation plan from prior context
2. Present the plan to the user and wait for approval (via chat)
3. Navigate to the `repo/` directory in the workspace
4. Make code changes following the plan
5. Run the test suite
6. If tests pass: commit, push, create draft PR via `gh pr create`
7. If tests fail: report failures and ask for guidance
8. Output structured JSON with result

**Key prompt sections:**
- Finding context (same as other agents)
- Prior agent outputs (enrichment, exposure, plan — injected by template)
- Workspace structure (repo is at `./repo/`)
- Git workflow instructions (branch naming, commit message format)
- PR creation instructions (use `gh pr create --draft`)
- Output contract (structured JSON)

**Test plan:**
- Template renders with finding context
- Template includes prior agent outputs
- Template includes repo-specific instructions

#### T5.2: Register remediation_executor in agent system
**Files touched:**
- `backend/cliff/agents/output_parser.py` — add `remediation_executor` schema
- `backend/cliff/agents/sidebar_mapper.py` — map executor output to sidebar "pull_request" section
- `backend/cliff/workspace/workspace_dir.py` — add to `AGENT_TYPES`, `AGENT_TYPE_TO_SECTION`, `CONTEXT_SECTIONS`
- `backend/cliff/models.py` — add `"remediation_executor"` to `AgentType` literal
- `backend/cliff/agents/executor.py` — add output contract and label for remediation_executor

**Change:** The remediation_executor uses **conversational delegation** (ADR-0024), not direct invocation. The executor needs a modified flow:
- Longer timeout (600s vs 120s)
- Tool use enabled (bash, edit, read, webfetch)
- Permission events surfaced to user
- Working directory set to workspace `repo/` subdirectory

Add a flag or separate execution path in `AgentExecutor.execute()` for tool-using agents. The core loop is the same (send prompt, collect SSE, parse output), but:
- The prompt doesn't include "no tool calls" instruction
- Timeout is higher
- Permission handling is active (already implemented in the executor)

**Test plan:**
- Unit: executor recognizes `remediation_executor` type
- Unit: output parser handles remediation-specific structured output
- Unit: sidebar mapper writes to "pull_request" section
- Unit: longer timeout applied for executor agent
- E2E: agent receives prompt with plan context, makes changes, creates PR (needs test repo)

#### T5.3: Plan approval flow (frontend)
**File:** `frontend/src/components/PlanApprovalCard.tsx` — new
**Change:** When the planner completes and the user clicks "Remediate", show a `PlanApprovalCard` in the chat:
- Displays the plan steps from the planner's structured output
- Shows the fix branch name
- "Approve and start" button → triggers `remediation_executor` agent execution
- "Modify plan" button → focuses the chat input for user to type modifications
- User can type modifications, agent re-presents updated plan

**Design:** Per UX-0001 Flow 5 wireframes.

**Files touched:**
- `frontend/src/components/PlanApprovalCard.tsx` — new
- `frontend/src/pages/WorkspacePage.tsx` — render PlanApprovalCard when planner output exists and "Remediate" clicked

**Test plan:**
- Card renders with plan steps
- "Approve and start" triggers executor API call
- Card transitions to execution progress view

#### T5.4: Remediation progress + completion card (frontend)
**File:** `frontend/src/components/RemediationResultCard.tsx` — new
**Change:** During execution, show live progress checklist (branch created, files changed, tests running, commit, push, PR). After completion, show the full result card with files changed, test results, and PR link.

**Design:** Per UX-0001 Flow 5 Step 2 (progress) and Step 3 (completion).

**Files touched:**
- `frontend/src/components/RemediationResultCard.tsx` — new (progress + completion states)
- `frontend/src/pages/WorkspacePage.tsx` — render during/after remediation executor

**Test plan:**
- Progress checklist updates during execution
- Completion card shows files changed, test results, PR link
- Test failure state shows guidance options

#### T5.5: Sidebar "Pull request" section
**File:** `frontend/src/components/WorkspaceSidebar.tsx`
**Change:** Replace "Owner" and "Ticket" sections with "Pull request" section:
- Shows: PR status (draft/open/merged), branch name, files changed, test results, PR link
- Before PR exists: "Not yet available" in muted italic
- After PR: structured display per UX-0001 Flow 6

**Files touched:**
- `frontend/src/components/WorkspaceSidebar.tsx` — replace sections
- `frontend/src/components/PRStatusBadge.tsx` — new (draft/open/merged badge)

**Test plan:**
- "Not yet available" when no PR data
- PR details rendered when sidebar has pull_request data
- PR link opens GitHub in new tab

#### T5.6: Update workspace opencode.json for tool-using agents
**File:** `backend/cliff/workspace/workspace_dir_manager.py`
**Change:** When the remediation executor will be used, the workspace `opencode.json` should have permissions set to `"ask"` for bash and edit (matching the permission-approval-ui flow). For analysis-only agents, keep current `"allow"` setting.

**Implementation:** Update `opencode.json` permission config based on whether the workspace has a cloned repo. If repo exists, set `bash: "ask"`, `edit: "ask"` so the permission approval UI handles tool approvals. If no repo, keep `"allow"` (analysis agents don't use tools).

**Test plan:**
- Unit: workspace with repo gets "ask" permissions
- Unit: workspace without repo keeps "allow" permissions

---

## WP6: Workspace status flow (G8)

**Team:** V1 (Agent Orchestrator) + V2 (App Builder)
**Effort:** Small
**Depends on:** WP5 (status transitions need PR creation events)
**Unblocks:** Nothing (final polish)

### V1 tasks

#### T6.1: Auto-advance finding status after agent completions
**File:** `backend/cliff/agents/executor.py` (or `backend/cliff/api/routes/agent_execution.py`)
**Change:** After successful agent execution, update the finding's status:
- After enricher completes: finding status → `triaged`
- After planner completes: finding status → `in_progress`
- After remediation_executor completes with PR: finding status → `remediated`
- User manually marks → `closed` (after merging PR)

**Files touched:**
- `backend/cliff/agents/executor.py` or `agent_execution.py` — add status transition after execution
- `backend/cliff/db/repo_finding.py` — verify `update_finding()` supports status changes

**Test plan:**
- Unit: enricher completion → finding status=triaged
- Unit: planner completion → finding status=in_progress
- Unit: executor with PR → finding status=remediated
- Unit: status doesn't regress (remediated → triaged should not happen)

#### T6.2: Store PR metadata in sidebar state
**File:** `backend/cliff/agents/sidebar_mapper.py`
**Change:** When `remediation_executor` output contains PR data, map to sidebar's "pull_request" section:
```python
{
    "pr_url": "https://github.com/.../pull/42",
    "pr_number": 42,
    "branch_name": "cliff/fix/cve-...",
    "status": "draft",
    "files_changed": [...],
    "test_results": {...}
}
```

**Test plan:**
- Unit: mapper extracts PR fields from executor output
- Unit: sidebar updated with pull_request section

### V2 tasks

#### T6.3: Status badge progression on Findings page
**File:** `frontend/src/pages/FindingsPage.tsx`, `frontend/src/components/FindingRow.tsx`
**Change:**
- Status badges use UX-0001 color scheme (new→neutral, triaged→secondary, in_progress→primary, remediated→tertiary, closed→neutral)
- PR link icon appears in the finding row when a PR exists (click opens GitHub)
- Status updates visible without full page refresh (TanStack Query invalidation after workspace actions)

**Test plan:**
- Each status renders with correct color token
- PR link icon shows when PR exists
- Polling/invalidation updates status without refresh

#### T6.4: Workspace top bar status display
**File:** `frontend/src/pages/WorkspacePage.tsx`
**Change:** Show current finding status in the workspace top bar with clear state label and color-coded badge.

---

## WP7: Structured result cards + error handling (G3 + G10)

**Team:** V2 (App Builder)
**Effort:** Medium
**Depends on:** Nothing for error handling; WP5 for remediation card (but other cards can start immediately)
**Runs in parallel with:** WP5 and WP6

#### T7.1: EnricherResultCard component
**File:** `frontend/src/components/EnricherResultCard.tsx` — new
**Change:** Structured card for enricher output:
- CVE ID(s), CVSS score with severity color bar, affected/fixed versions, exploit status
- Confidence badge (●●●○ High/Medium/Low)
- Expandable "View details" section
- Design per UX-0001 Flow 4

#### T7.2: ExposureResultCard component
**File:** `frontend/src/components/ExposureResultCard.tsx` — new
**Change:** Structured card for exposure analyzer output:
- Reachability, environment, internet-facing, criticality
- Import chain visualization
- Urgency bar
- Confidence badge

#### T7.3: PlannerResultCard component
**File:** `frontend/src/components/PlannerResultCard.tsx` — new
**Change:** Structured card for planner output:
- Numbered fix steps
- Interim mitigation
- Effort estimate
- Definition of done checklist
- Confidence badge

#### T7.4: ConfidenceBadge component
**File:** `frontend/src/components/ConfidenceBadge.tsx` — new
**Change:** Reusable confidence indicator used in all result cards:
- High: ●●●● in tertiary color
- Medium: ●●○○ in secondary color
- Low: ●○○○ in error color
- Maps from 0.0-1.0 confidence score

#### T7.5: Wire result cards into chat timeline
**File:** `frontend/src/pages/WorkspacePage.tsx`
**Change:** When rendering agent messages in the chat, check for structured output. If present, render the typed result card instead of the generic `ResultCard` (markdown). Fall back to `ResultCard` when structured data isn't available.

**Logic:**
```tsx
if (message.agent_type === "finding_enricher" && message.structured_output) {
  return <EnricherResultCard data={message.structured_output} />;
}
// ... similar for other agent types
// fallback:
return <ResultCard markdown={message.content} />;
```

#### T7.6: ErrorState component
**File:** `frontend/src/components/ErrorState.tsx` — new
**Change:** Error display component (per UX-0001):
- Icon: `error_outline` in `text-error`
- Title: `text-on-surface font-headline font-bold`
- Subtitle: `text-on-surface-variant`
- Retry button: outline style
- Same centered layout as existing `EmptyState`

#### T7.7: Error boundaries on all pages
**File:** `frontend/src/pages/*.tsx`
**Change:** Wrap each page component in a React error boundary that catches render errors and shows `ErrorState` with "Reload page" CTA. Also add API error handling in TanStack Query hooks — show `ErrorState` when queries fail.

**Files touched:**
- `frontend/src/components/ErrorBoundary.tsx` — new (generic error boundary wrapper)
- `frontend/src/pages/FindingsPage.tsx` — wrap in boundary, add query error handling
- `frontend/src/pages/WorkspacePage.tsx` — wrap in boundary
- `frontend/src/pages/HistoryPage.tsx` — wrap in boundary
- `frontend/src/pages/SettingsPage.tsx` — wrap in boundary

**Test plan:**
- Error boundary catches render errors, shows ErrorState
- Retry button reloads the page
- API errors show ErrorState with retry
- Retry triggers query refetch

#### T7.8: Card design system compliance
**All new components** must follow Serene Sentinel rules:
- No `1px solid` borders — use `shadow-sm` or tonal bg shifts
- `bg-surface-container-lowest` card background
- `rounded-2xl rounded-bl-md` for assistant message cards
- Section labels: `text-xs font-semibold text-on-surface`
- Values: `text-sm text-on-surface-variant`
- Agent label: `text-[10px] font-bold uppercase tracking-widest text-on-surface-variant`

**Test:** Visual review against UX-0001 wireframes.

---

## Database changes

**No schema migrations needed.** The existing `AgentRun`, `SidebarState`, and `Finding` tables already support all needed fields:
- `AgentRun.agent_type` accepts any string (add `"remediation_executor"` to the Pydantic literal)
- `AgentRun.structured_output` is a JSON field (handles executor's PR data)
- `SidebarState` sections are JSON (new "pull_request" section fits)
- `Finding.status` already supports the full lifecycle

**Settings storage:** Repo URL stored via existing `AppSetting` table. GitHub PAT stored via existing `Credential` table (AES-256 encrypted).

---

## Test strategy

### Unit tests (per work package)

Each WP adds unit tests as described in individual tasks. Key coverage areas:
- **WP2:** Repo cloning (mock subprocess), URL token injection, branch naming, error handling
- **WP4:** Pipeline sequence, suggest-next logic with 4-agent flow
- **WP5:** Executor output parsing, sidebar mapping for PR data, prompt building for tool-using agent
- **WP6:** Status transitions, no-regression guard
- **WP7:** Component rendering (snapshot or RTL tests for result cards)

**Target:** All existing 187 unit tests continue passing. Each WP adds 10-20 new tests.

### E2E tests

- **Repo clone E2E:** Create workspace with repo URL pointing to a test repo (e.g., a small fixture repo in the Cliff org). Verify `repo/` directory created with correct branch.
- **Full pipeline E2E:** Import finding → enrich → expose → plan → remediate → PR created. Requires real LLM + real GitHub repo. Gate: this is the "it works" test.
- **Error scenarios:** Clone failure (bad URL), test failure during remediation, PR creation failure (invalid token).

**Target:** 5-10 new E2E tests. Only run with `OPENAI_API_KEY` + `GH_TOKEN` + test repo configured.

---

## Rollout sequence

The WPs map to 4-5 PRs on feature branches:

| PR | WPs | Title | Reviewer |
|---|---|---|---|
| PR 1 | WP1 | feat: Docker first-run + demo mode + gh CLI | @galanko |
| PR 2 | WP2 + WP4 | feat: repo cloning + pipeline update (4-agent MVP) | @galanko |
| PR 3 | WP3 | feat: import UX + first-run onboarding | @galanko |
| PR 4 | WP5 | feat: remediation agent + PR creation (hero feature) | @galanko |
| PR 5 | WP6 + WP7 | feat: status flow + result cards + error handling | @galanko |

PRs 1 and 3 can merge independently (no cross-dependency). PRs 2 and 4 are sequential. PR 5 can land last.

---

## Risk register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| `gh` CLI not in OpenCode sandbox | PR creation blocked | Medium | Test early; fall back to `git push` + `curl` to GitHub API |
| Shallow clone breaks agent (needs git history) | Agent can't determine what changed | Low | Agent can `git fetch --unshallow` on demand; add to prompt |
| Agent creates bad PRs (wrong files, broken tests) | User trust eroded | Medium | Plan approval step; permission UI for every tool use; draft PRs |
| Large repos slow down workspace creation | UX feels sluggish | Medium | Shallow clone; future: async clone with progress |
| OpenCode process doesn't support chat mid-agent | Collaborative model breaks | Low | Test early with current OpenCode; fallback: new session after agent completes |
| Token with insufficient scopes | Clone/PR creation fails silently | Medium | "Test connection" validates scopes upfront |

---

_This implementation plan follows the Cliff architecture workflow. After CEO approval, V1 (Agent Orchestrator) and V2 (App Builder) execute in parallel using `/cliff-agent-orchestrator` and `/app-builder` skills._
