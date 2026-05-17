# ADR-0024: Repository cloning and agentic remediation

**Date:** 2026-04-09
**Status:** Proposed
**PRD:** PRD-0001 (MVP — minimum value product)

## Context

Cliff's current workspace runtime (ADR-0014) creates isolated directories with finding context files, agent definitions, and per-workspace OpenCode processes. Agents analyze findings using context documents but have no access to actual source code. The remediation planner *describes* fix steps but cannot execute them.

PRD-0001 redefines the MVP's definition of done: instead of producing advisory remediation plans, Cliff must **actually fix the code and create a draft PR on GitHub**. This requires two new capabilities:

1. **Repository access** — the workspace must contain a clone of the target repository so agents can read, modify, and test the codebase.
2. **Agentic remediation** — a new agent type that writes code changes, runs tests, commits, pushes, and creates a draft PR via the GitHub API.

These are the most significant architectural additions since workspace isolation (ADR-0014) and the agent execution model (ADR-0021).

## Decision

### 1. Repository access via agent tooling

**The agent clones the repository itself** using bash and git, not custom backend code. The backend's only responsibility is making the GitHub PAT available as an environment variable (`GH_TOKEN`) in the workspace's OpenCode process.

**Why agent-driven, not backend-driven:**

- The workspace OpenCode process already has bash access — the agent can run `git clone`, `git checkout -b`, `git push`, and `gh pr create` naturally.
- This follows the Claude Code model: the AI uses tools to interact with the codebase, not custom middleware.
- It eliminates ~100 lines of subprocess wrapper code (URL token injection, branch management, pull-on-reopen) that the LLM handles better.
- The agent can make intelligent decisions about clone depth, branch naming, and error recovery without us encoding every edge case.

**What the backend provides:**

1. **Settings storage:** Repo URL stored in `AppSetting` table, GitHub PAT stored in `Credential` table (AES-256 encrypted, ADR-0016).
2. **Environment injection:** `GH_TOKEN` env var set when starting the workspace OpenCode process, sourced from the credential vault.
3. **Agent prompt context:** The remediation executor template includes the repo URL and instructions to clone into the workspace directory.

**Directory layout after agent clones:**

```
data/workspaces/<workspace-id>/
├── opencode.json              # Workspace OpenCode config
├── CONTEXT.md                 # Auto-generated finding context
├── .opencode/agents/          # Rendered agent definitions
├── context/                   # Agent output JSON files
│   ├── finding.json
│   ├── enrichment.json
│   └── ...
├── history/
│   └── agent-runs.jsonl
└── repo/                      # ← Cloned by the agent via bash
    ├── .git/
    ├── package.json
    ├── src/
    └── ...
```

**Key design choices:**

- **Agent handles git workflow:** Clone, branch creation (`cliff/fix/<finding-slug>`), commits, push, PR creation — all via bash and `gh` CLI.
- **Repository URL and PAT** stored as a global setting in the credential vault (reusing ADR-0016 infrastructure). One repo for MVP; per-finding override is a future feature.
- **No custom clone code in Python.** The `WorkspaceDirManager` is unchanged. The agent prompt instructs the LLM to clone into `./repo/` as its first step.
- **Pull on reopen** — the agent checks if `repo/` exists and pulls latest instead of re-cloning. This is part of the prompt, not backend logic.

**What doesn't change:** Context files, agent definitions, agent-runs log, and `WorkspaceDirManager` remain in their current locations and code. The `repo/` subdirectory is created by the agent at runtime.

### 2. Remediation executor agent

A new agent type `remediation_executor` joins the pipeline after `remediation_planner`. Unlike the existing 5 agents (which use direct invocation with structured JSON output, per ADR-0021), the remediation executor uses **conversational delegation** — it is a long-running, tool-using agent that interacts with the codebase.

**Execution model:**

| Aspect | Existing agents (enricher, exposure, planner) | Remediation executor |
|--------|-----------------------------------------------|---------------------|
| Mode | Direct invocation (one prompt → one JSON response) | Conversational (multi-turn, tool-using) |
| Tools | None (pure analysis) | bash, edit, read, webfetch |
| Duration | 10-30 seconds | 1-10 minutes |
| Output | Structured JSON (parsed by output_parser) | Structured JSON + side effects (code changes, commits, PR) |
| Permission model | N/A (no tool use) | Workspace `opencode.json` set to `"ask"` for bash/edit; user approves via permission UI |
| Timeout | 120s default | 600s (10 minutes) |

**Agent prompt contract:**

The remediation executor receives:
- Finding context (same as other agents)
- Prior agent outputs (enrichment, exposure, plan)
- Explicit instructions to: (a) present the plan for approval, (b) make code changes in `repo/`, (c) run tests, (d) commit and push, (e) create a draft PR via `gh pr create`

**Output schema** extends the standard agent output with remediation-specific fields:

```json
{
  "summary": "string",
  "result_card_markdown": "string",
  "confidence": 0.0-1.0,
  "structured_output": {
    "status": "pr_created | tests_failed | needs_guidance | error",
    "branch_name": "cliff/fix/cve-...",
    "files_changed": [{"path": "...", "additions": N, "deletions": N}],
    "test_results": {"passed": N, "failed": N, "summary": "..."},
    "pr_url": "https://github.com/.../pull/N" | null,
    "pr_number": N | null,
    "commit_sha": "abc123" | null
  }
}
```

**Collaborative model:**

The executor does NOT auto-run. After the planner completes:
1. Frontend shows a `PlanApprovalCard` with the plan steps and an "Approve and start" button.
2. On approval, the `remediation_executor` agent starts via the existing execution API.
3. During execution, the agent may request tool-use permissions (surfaced via the permission approval UI from `feat/permission-approval-ui`).
4. The user can chat mid-execution to steer the agent (using the existing workspace chat — messages are forwarded to the same OpenCode session).
5. After the agent finishes, it writes a final JSON output that the output parser handles like any other agent.

**Trust boundary:**

- The agent creates a **draft PR** — never merges.
- The `opencode.json` permission model is set to `"ask"` for bash and edit, so every file modification and command requires user approval (or auto-approval if the user trusts the agent).
- For MVP dogfooding, permissions can be set to `"allow"` to reduce friction. The UI supports both modes.

### 3. GitHub integration

**All git and GitHub operations are performed by the agent** via bash, using `git` and `gh` CLI. The agent runs commands like:

```bash
git clone https://github.com/owner/repo.git repo/
cd repo && git checkout -b cliff/fix/cve-2024-48930
# ... make changes, run tests ...
git commit -m "fix: lodash prototype pollution (CVE-2024-48930)"
git push -u origin cliff/fix/cve-2024-48930
gh pr create --draft --title "fix: ..." --body "..." --base main
```

`gh` and `git` authenticate using the `GH_TOKEN` environment variable, injected by the backend from the credential vault into the workspace OpenCode process.

**Token scope requirements:** `repo` (full repo access — clone, push, PR create). Documented in the Settings UI.

### 4. Pipeline update

The MVP pipeline becomes 4 agents:

```
enricher → exposure_analyzer → remediation_planner → remediation_executor
```

`owner_resolver` is excluded (open-source maintainer is the owner). `validation_checker` remains available on-demand but is not in the suggested pipeline — validation happens by re-running the scanner after merging PRs.

`suggest_next()` updated to reflect this 4-agent pipeline. After `remediation_executor` completes with a PR, the suggestion is "Review PR on GitHub" (not another agent).

## Consequences

### What becomes easier

- **End-to-end value** — Cliff goes from advisory to agentic. A single session can go from "I have a finding" to "I have a PR."
- **Dogfooding** — the MVP persona (open-source maintainer) can test the full loop on a real repo.
- **Trust via visibility** — the draft PR on GitHub is the trust artifact. The user reviews real diffs, not plans.

### What becomes harder

- **Workspace disk usage** — each workspace now contains a full repo clone (~50-500 MB). Shallow clones mitigate this but don't eliminate it. Need to consider cleanup for closed workspaces.
- **Network dependency** — workspace creation now requires network access (git clone). Failure handling needed for offline/slow connections.
- **Agent complexity** — the remediation executor is significantly more complex than analysis agents. It uses tools, modifies files, and interacts with external services (GitHub). Failure modes multiply.
- **Test strategy** — E2E tests for the remediation executor need a real GitHub repo (or a mock git remote). Unit tests can mock the git operations.
- **Security surface** — the agent can execute arbitrary bash commands in the workspace. The permission model (ask/allow) is the guardrail. For the community edition this is acceptable (single user, own repo).

### What doesn't change

- Existing agents (enricher, exposure, planner, validation) continue to work as-is.
- The workspace isolation model (ADR-0014) is preserved — each workspace still gets its own directory and process.
- The agent execution API (`POST /workspaces/{id}/agents/{type}/execute`) works for all agent types, including the new executor.
- Database schema is unchanged — `AgentRun` already supports all needed fields.
- Frontend architecture is unchanged — new components (result cards, plan approval) are additive.

### Risks

| Risk | Mitigation |
|------|-----------|
| Clone takes too long for large repos | Shallow clone + future: async clone with progress UI |
| Agent makes bad code changes | Draft PR (never auto-merge) + permission approval for each tool use |
| `gh` CLI not available in all environments | Include in Docker image; document for local dev; fall back to git push + API call if needed |
| PAT scope too broad | Document minimum required scopes; future: GitHub App with fine-grained permissions |
| Workspace disk fills up | Archive + delete closed workspace directories; shallow clones reduce footprint |
