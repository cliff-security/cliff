# PRD-0001: MVP — minimum value product

**Status:** Approved
**Author:** Product team
**Date:** 2026-04-09
**Approver:** @galanko (CEO)

---

## Problem statement

Cliff has a working engine — agents run, workspaces isolate, findings persist, the UI renders. But no real user has ever used it to actually *fix* a real vulnerability. We have technology but not yet a product.

The original vision framed Cliff as an advisory copilot: understand findings, plan fixes, export plans. That's useful but not transformative. The real value — the thing that makes Cliff the "Claude Code for security" — is going all the way: **understand the finding, write the fix, create the PR, close the vulnerability.** Not "here's what you should do." Instead: "I did it, here's the PR, review and merge."

This PRD defines the minimum set of work needed to make Cliff deliver that end-to-end value against a real open-source repository with real Snyk findings. The measure of success is not "it produced nice plans" but "it actually remediated findings and created mergeable PRs."

## User persona

**MVP persona: Open-source maintainer responsible for security posture**

Gal (CEO, dogfooding) — A developer who maintains an open-source project and is responsible for keeping it clean of security findings. Uses Snyk (free tier) to scan the repo for dependency vulnerabilities and code issues. Knows how to read CVEs and update packages, but the tedious part is the full remediation cycle: understanding each finding's real impact, figuring out the right fix, actually making the code change, verifying it works, and creating a PR — all while context-switching between the scanner dashboard, CVE databases, package registries, and the codebase.

The MVP persona is not "enterprise security engineer" — it's someone who owns both the code and the security posture. They don't need approval workflows, team routing, or owner resolution. They need to go from "I have 20 open findings" to "I have 20 PRs ready to merge."

**What this persona cares about:**

- "Is this finding actually exploitable in my project, or just noise?"
- "What's the concrete fix — upgrade to which version, change which code?"
- "Can you just *make the fix* and open a PR for me to review?"
- "Am I making progress through my queue, or am I going in circles?"

**Next persona (post-MVP):** A security engineer at a mid-size company who manages 50-200 open findings and spends most of their day context-switching between scanner dashboards, CMDBs, Jira, and Slack. They need a single place to work through their queue. This persona needs ticketing integration, team routing, and approval workflows — all out of scope for MVP.

## Value hypothesis

> If an open-source maintainer can import Snyk findings, and for each one have AI agents understand the vulnerability, write the actual code fix, and create a draft PR — all from a single chat interface — they will clear their security backlog in a fraction of the time it takes to do it manually.

The MVP proves or disproves this hypothesis. Everything in scope serves this test. Everything out of scope doesn't.

## Dogfooding scenario

**Input:** Snyk JSON export from the Cliff repository itself (or another open-source project Gal maintains).

**Setup:** User configures a GitHub repo URL and a personal access token in Settings. Cliff clones the repo into each workspace directory when a finding is opened for remediation.

**Session goal:** Import all findings, work through them one-by-one: enrich (understand the CVE), analyze exposure (is it real in this repo?), plan the fix, execute the fix (agent modifies code), and create a draft PR on GitHub. Human reviews and merges each PR.

**What "done" looks like:** Every finding in the batch has either (a) a draft PR on GitHub with the fix, ready for human review and merge, or (b) a documented "accepted risk" / "false positive" justification. The Snyk scan, re-run after merging the PRs, shows a clean or significantly reduced finding count.

**The end-to-end loop:**
1. Snyk scans repo → produces findings JSON
2. Import findings JSON into Cliff
3. For each finding: Enrich → Analyze → Plan → Remediate (agent writes fix) → Create PR
4. Human reviews and merges PRs
5. Re-run Snyk scan → findings are resolved
6. Finding status in Cliff → closed

## What exists today (gap analysis)

### Works end-to-end

| Capability | Status | Notes |
|---|---|---|
| Findings CRUD (backend) | Complete | Create, list, filter, sort, update, delete |
| Findings page (frontend) | Complete | Table with severity/status filters, sort, "Solve" button |
| Workspace lifecycle | Complete | Create from finding, isolated directory + process, chat via SSE |
| 5 agents (enricher, owner, exposure, planner, validator) | Complete | Prompt templates, output schemas, sidebar mapping. Owner resolver excluded from MVP pipeline |
| Agent execution API | Complete | POST execute, GET suggest-next, POST cancel, SSE progress |
| Workspace sidebar | Complete | Summary, evidence, owner, plan, definition of done, validation |
| History page | Complete | List, filter, search, export to markdown, reopen |
| Async finding ingest + LLM normalizer | Complete | Chunked background processing, any scanner format |
| Docker build | Complete | Multi-stage, supervisord, health checks |
| Database + migrations | Complete | SQLite WAL, all entities, full CRUD |
| Integration registry + credential vault | Complete | 6 vendors defined, encrypted credential storage |

### Gaps blocking MVP value

| Gap | Why it blocks value | Effort estimate |
|---|---|---|
| **G1: Import UX** — No file upload in frontend. Ingest API exists but user has no way to feed it from the browser | User can't bring their own findings. Dead on arrival without this | Small (frontend form + API call) |
| **G2: First-run onboarding** — No guidance when app starts empty. User sees blank findings page with no idea what to do | First impression is "this is empty and I don't know how to start" | Small (empty state + guided import prompt) |
| **G3: Agent result cards** — Agent output renders as raw markdown blobs. No structured cards with headers, confidence, evidence sections | Results look unpolished and are hard to scan. Undermines trust in agent quality | Medium (component work per agent type) |
| **G4: "What's next?" guidance** — `suggest_next()` exists in backend but frontend doesn't surface it. User has to guess which agent to run | Breaks the guided experience. User shouldn't need to know the agent pipeline | Small (wire existing API to UI) |
| **G5: Repo cloning into workspace** — Workspaces currently have finding context files but NOT the actual source code. Agent can't fix code it can't see | Without repo access, the "remediate" step is impossible. This is the critical new gap | Medium (clone on workspace create, branch management) |
| **G6: Remediation agent** — No agent exists that actually writes code fixes. Current planner *describes* fixes but doesn't execute them | The entire value proposition depends on this. This is the hero feature | Large (new agent definition + execution flow + git operations) |
| **G7: PR creation from workspace** — No mechanism to push a branch and create a GitHub PR from within a workspace | Without this, the fix stays local and the user has to do the git work manually | Medium (GitHub token config, git push, `gh pr create`) |
| **G8: Workspace status flow** — No explicit status progression. Finding goes from new → in_progress when workspace opens but never progresses | User can't track which findings they've actually finished working on | Small (status transitions after key agent runs) |
| **G9: Docker first-run** — No startup migration runner, no demo mode | Can't `docker run` and have it work. Blocks self-hosted deployment | Small (entrypoint script + seed flag) |
| **G10: Error handling UX** — No error boundaries, no retry buttons, no feedback when agents fail | When something goes wrong (and it will with LLM calls), user sees a blank screen or cryptic error | Medium (ErrorState component + boundaries) |

### Explicitly not blocking MVP

| Item | Why it can wait |
|---|---|
| Owner Resolver agent | Open-source maintainer *is* the owner. No routing needed. Bring back for enterprise persona |
| Ticketing integration (Jira, Linear) | The output is a PR, not a ticket. Ticketing is an enterprise persona need |
| Plan export / copy-as-issue | Superseded by the PR creation flow. The PR *is* the work product |
| Real scanner API adapters (Snyk, Tenable APIs) | JSON upload + LLM normalizer handles any format. API adapters are a scaling feature |
| Design system compliance (P5 backlog) | Visual polish matters but doesn't block the value test. Fix after MVP is proven |
| Settings page mockup drift | Current settings work. Fancy tabs are post-MVP |
| Sentinel Insights sidebar on Findings | Nice-to-have AI summary. Findings list + agents already provide this per-workspace |
| Multi-user / RBAC | Single-user dogfooding. By definition not needed yet |
| Permission approval UI | Agents run with auto-approve for now. Trust UX is post-MVP |
| Search by CVE on findings page | Filter by severity + sort covers dogfooding. Search is a scale feature |
| Batch agent runs | One finding at a time for MVP. Batch is a future feature request |

## User stories

### Story 1: Import my findings

**As** an open-source maintainer, **I want to** upload a Snyk JSON export of my repo's vulnerabilities, **so that** I can start working on them in Cliff without manual data entry.

**Given** I'm on the Findings page,
**When** I click "Import findings" and upload my Snyk JSON export (or paste the JSON),
**Then** the system normalizes the data, shows me an import progress bar, and the findings appear in my queue within seconds.

**The user should feel:** "That was easy. It understood Snyk's format without me configuring anything."

**Acceptance criteria:**

- [ ] "Import findings" button permanently visible in the Findings page toolbar (not just empty state)
- [ ] When the queue is empty, the empty state also prominently features the import action with guidance text
- [ ] File upload accepts `.json` files up to 10MB
- [ ] Paste-JSON option available as alternative to file upload
- [ ] Progress indicator shows chunks processed / total
- [ ] Import errors show which findings failed and why, without losing successful ones
- [ ] Imported findings appear in the queue immediately as they're processed (not just after the full batch)
- [ ] Tested with real Snyk JSON export format as primary target
- [ ] Also works with other scanner JSON formats (Wiz, generic) via LLM normalizer

### Story 2: Understand what to do first

**As** an open-source maintainer looking at a queue of 20+ findings, **I want to** quickly understand which findings are most urgent and start working on the most critical one, **so that** I spend my time on what matters.

**Given** I've imported findings,
**When** I view the Findings page,
**Then** findings are sorted by severity (critical first), I can see status at a glance, and I can click "Solve" to open a workspace for any finding.

**The user should feel:** "I know where to start. The system is helping me prioritize."

**Acceptance criteria:**

- [ ] Default sort is severity descending (critical → high → medium → low)
- [ ] Status badges clearly show finding state (new, triaged, in_progress, remediated, validated, closed)
- [ ] "Solve" button on each finding row opens (or resumes) the workspace for that finding
- [ ] Findings page loads in under 2 seconds with 100 findings

### Story 3: Connect my repo

**As** an open-source maintainer, **I want to** tell Cliff which GitHub repo to work on, **so that** agents can access my source code and create PRs.

**Given** I'm in Settings (or first-run onboarding),
**When** I enter my GitHub repo URL and personal access token,
**Then** Cliff validates the connection and stores the credentials. When I open a workspace, the repo is cloned into the workspace directory automatically.

**The user should feel:** "Setup was quick. Now Cliff has everything it needs to actually fix my code."

**Acceptance criteria:**

- [ ] Settings page has a "Repository" section: GitHub repo URL + personal access token fields
- [ ] "Test connection" button validates the token has repo access (clone + push + PR creation permissions)
- [ ] Token stored securely in the existing credential vault
- [ ] When a workspace is created for a finding, the repo is cloned into the workspace directory
- [ ] Clone happens on a fresh branch named `cliff/fix/<finding-slug>` (e.g., `cliff/fix/cve-2026-1234`)
- [ ] Clone is shallow (depth=1) for speed; full history fetched only if agents need git log
- [ ] If the repo is already cloned (workspace reopened), pull latest from main instead of re-cloning
- [ ] Workspace context (CONTEXT.md) includes repo structure overview so agents understand the codebase

### Story 4: Guided remediation pipeline

**As** an open-source maintainer in a workspace, **I want** the system to guide me through the full remediation pipeline step by step, **so that** I go from "unknown finding" to "PR ready for review" without guessing what to do next.

**Given** I've opened a workspace for a critical finding (repo cloned automatically),
**When** I start working,
**Then** the system recommends the next step at each stage: enrich → analyze exposure → plan fix → execute fix → create PR.

**The user should feel:** "It's guiding me through the entire process, from understanding the problem to having a fix ready."

**MVP agent pipeline (4 agents, Owner Resolver excluded):**
1. **Finding Enricher** — Understand the CVE: severity, exploit status, affected/fixed versions
2. **Exposure Analyzer** — Is this actually exploitable in *this* repo? Reachability, import chains, environment
3. **Remediation Planner** — Concrete fix plan: upgrade to version X, modify file Y, run tests
4. **Remediation Executor** — Actually make the code changes, run tests, create the PR (NEW — see Story 6)

Validation Checker remains available but is invoked after the PR is merged and Snyk is re-run — it's a post-fix verification, not part of the core pipeline.

**Acceptance criteria:**

- [ ] On workspace open, the suggested action is "Enrich this finding" (visually highlighted)
- [ ] After each agent completes, the next recommended action chip is visually emphasized
- [ ] Pipeline sequence: Enrich → Analyze Exposure → Plan → Remediate (execute fix + PR)
- [ ] User can always override suggestions and run any agent in any order
- [ ] The `suggest_next()` API response drives the UI — no hardcoded frontend logic
- [ ] After the remediation agent creates a PR, the suggestion shifts to "Review PR on GitHub" with a link

### Story 5: See structured, trustworthy results

**As** an open-source maintainer, **I want** agent results to be presented as clear, structured cards (not raw markdown walls), **so that** I can quickly scan the key information and trust the output.

**Given** the Finding Enricher has completed,
**When** I look at the chat timeline,
**Then** I see a structured result card with sections (CVE details, severity, exploit info, fix version) and a confidence indicator — not a blob of markdown. The sidebar also updates with the accumulated state.

**The user should feel:** "This is professional and trustworthy. I can scan the key points in 5 seconds."

**UX decision: Cards in chat, sidebar as persistent reference.**
The chat is the timeline — it shows structured cards inline as agents complete. The sidebar accumulates the full detail across all agent runs. Chat tells the story; sidebar holds the truth. This means:
- Chat cards are compact: headline info, key data points, confidence badge
- Sidebar sections show full detail: all fields, expandable evidence, references
- If the user re-runs an agent, the chat shows both runs (history), the sidebar shows only the latest (truth)

**Acceptance criteria:**

- [ ] Each agent type has a dedicated result card layout in the chat (not generic markdown rendering)
- [ ] Enricher card: CVE ID(s), CVSS score with severity color, affected/fixed versions, exploit status, references
- [ ] Exposure card: environment, internet-facing status, reachability, business criticality, urgency
- [ ] Planner card: numbered fix steps, interim mitigation, effort estimate, definition of done checklist
- [ ] Remediation card: files changed, diff summary, test results, PR link (when created)
- [ ] Confidence indicator visible on each card (high/medium/low with appropriate color)
- [ ] Cards are scannable — critical info is in headers/badges, details are expandable
- [ ] Sidebar sections update after each agent run with the full structured output
- [ ] One-at-a-time execution: only one agent runs at a time per workspace (batch mode is post-MVP)

### Story 6: Agent fixes my code and creates a PR

**As** an open-source maintainer, **I want** the remediation agent to actually write the code fix, verify it works, and create a draft PR on GitHub, **so that** I just need to review and merge — not do the tedious work myself.

**Given** the Remediation Planner has produced a fix plan (e.g., "upgrade lodash from 4.17.20 to 4.17.21"),
**When** I click "Remediate" (or the pipeline suggests it as the next step),
**Then** the agent:
1. Presents the fix plan in chat and asks for approval before executing
2. On approval, creates a fix branch (`cliff/fix/<finding-slug>`)
3. Makes the code changes (e.g., updates `package.json`, runs `npm install`, updates lockfile)
4. Runs the full test suite and reports results
5. Commits with a descriptive message referencing the CVE
6. Pushes the branch and creates a draft PR on GitHub
7. Reports back with: files changed, test results, and a link to the PR

**The user should feel:** "It showed me the plan, I approved it, and it did the work. And when something wasn't right, I just told it in the chat and it adjusted."

**Interaction model: Collaborative, like Claude Code.**
This is NOT a fire-and-forget automation. The workspace chat is a live collaboration surface:
- Agent presents plan → user approves, adjusts, or redirects
- Agent executes fix → if tests fail, agent reports and asks for guidance
- User can chat mid-execution: "actually, don't upgrade that package, pin it to 4.17.20 and add a WAF rule instead"
- Agent adapts based on conversation context
- Only when the user is satisfied does the agent push and create the PR

**Trust model: Propose, don't merge.**
The agent creates a *draft* PR. The human reviews the diff on GitHub, checks test results, and decides to merge. This keeps the human in the loop on every code change while eliminating the tedious research and coding work.

**Acceptance criteria:**

- [ ] "Remediate" action chip available after the planner has run
- [ ] Agent presents the fix plan in chat and waits for user approval before executing
- [ ] User can modify the plan via chat before approving (e.g., "use version 4.17.21 instead of 4.18.0")
- [ ] Agent creates a branch named `cliff/fix/<finding-slug>` from latest `main`
- [ ] Agent makes code changes guided by the (possibly user-modified) remediation plan
- [ ] Agent runs the full test suite by default (e.g., `npm test`, `pytest`) and reports results in chat
- [ ] If tests fail, agent reports the failure and asks for user guidance — does NOT push a broken branch
- [ ] User can chat with the agent mid-execution to steer, correct, or redirect (Claude Code model)
- [ ] Agent commits changes with message format: `fix: <finding title> (CVE-XXXX-YYYY)\n\nRemediation by Cliff`
- [ ] Agent pushes branch to GitHub remote
- [ ] Agent creates a draft PR with: title, description (from enricher + planner), test results, and CVE references
- [ ] PR link is displayed in the workspace chat as a result card and persisted to sidebar
- [ ] If the fix is not straightforward (e.g., requires architectural changes), agent attempts best-effort and explains trade-offs. User can guide further via chat
- [ ] Workspace sidebar shows PR status: branch name, PR URL, PR state (draft/open/merged)

### Story 7: Track my progress across the queue

**As** an open-source maintainer working through a batch of findings, **I want to** see which findings I've analyzed, fixed, and had PRs created for, **so that** I can track my progress toward a clean repo.

**Given** I've worked on several findings,
**When** I return to the Findings page,
**Then** I see updated status badges showing the remediation state: analyzed, PR created, merged/closed.

**The user should feel:** "I can see my progress. I'm making a dent in this queue. 12 of 20 findings now have PRs."

**Acceptance criteria:**

- [ ] Finding status auto-advances based on agent completions: new → triaged (after enricher), triaged → in_progress (after planner), in_progress → remediated (after PR created), remediated → closed (user marks as merged/resolved)
- [ ] Status transitions are visible on the Findings page without refresh
- [ ] Workspace top bar shows current finding status with clear state label
- [ ] Findings with PRs show a GitHub link icon in the queue row
- [ ] History page shows completed findings with PR links and outcome summary

## Success metrics

| Metric | Target | How measured |
|---|---|---|
| End-to-end completion | Import real Snyk findings, get draft PRs created for the majority of fixable findings | Manual dogfooding session |
| Time-to-PR per finding | Under 10 minutes from "Solve" to having a draft PR on GitHub (agents + review) | Stopwatch during dogfooding |
| PR quality | >70% of agent-created PRs are mergeable with minor or no human edits | CEO review of PR diffs |
| Agent success rate | >80% of agent runs produce valid, useful structured output | Count parse successes vs. failures in agent_run DB table |
| Findings cleared | After merging PRs and re-running Snyk, >50% of original findings are resolved | Before/after Snyk scan comparison |
| Zero show-stoppers | No crashes, blank screens, or lost state during a 1-hour session | Manual session with notes |
| Self-serve setup | `docker compose up` → working app with import + repo config in under 10 minutes | Timed cold start |

## Scope

### In scope (MVP must-haves)

- **G1:** Finding import UX — file upload + paste JSON on Findings page
- **G2:** First-run onboarding — empty state with guided import prompt + repo setup
- **G3:** Structured agent result cards — per-agent card layouts replacing raw markdown
- **G4:** "What's next?" guidance — wire `suggest_next()` to frontend, updated pipeline (no Owner Resolver)
- **G5:** Repo cloning into workspace — clone GitHub repo on workspace create, branch management
- **G6:** Remediation agent — new agent that writes code fixes guided by the planner's output
- **G7:** PR creation from workspace — push branch, create draft PR via GitHub API/CLI
- **G8:** Workspace status flow — auto-advance finding status, including "PR created" state
- **G9:** Docker first-run — startup migrations + seed demo mode
- **G10:** Error handling UX — ErrorState component, error boundaries on all pages, retry buttons

### Out of scope (post-MVP)

- Owner Resolver agent — maintainer is the owner. Bring back for enterprise persona
- Ticketing integration (Jira, Linear) — the output is a PR, not a ticket
- Plan export / copy-as-issue — superseded by PR creation
- Real scanner API adapters — JSON upload handles any format
- Design system compliance cleanup — visual polish, not value
- Settings page redesign — current settings work
- Permission approval UI — agents auto-approve for dogfooding
- Multi-user, RBAC, SSO — single-user edition
- Sentinel Insights sidebar — per-workspace agents already provide this
- Search by CVE — filter + sort covers dogfooding scale
- Batch agent runs — one finding at a time
- Validation Checker as pipeline step — available on-demand but not in the core pipeline. Validation happens by re-running Snyk after merging PRs

## Dependencies

**Upstream (already complete):**

- Phase 3: persistence + domain model
- Phase 5: workspace runtime with isolated processes
- Phase 6a: agent definitions + templates
- Phase 6b: agent orchestration engine (executor, pipeline, suggest_next)
- Async finding ingest with LLM normalizer (ADR-0022, ADR-0023)
- Integration registry + credential vault (for storing GitHub token)

**Downstream (unblocked by MVP):**

- Phase 7: ticketing workflow — for enterprise persona who needs Jira/Linear tickets instead of PRs
- Phase 9b: packaging finalization — MVP includes Docker first-run, 9b adds tagged release + upgrade docs
- v0.2 features: Owner Resolver, batch mode, real scanner adapters, permission UI, design polish

**Cross-team:**

- G1 (import UX) and G2 (onboarding): App Builder (frontend)
- G3 (result cards): App Builder frontend + Agent Orchestrator (output format)
- G4 (suggest-next + pipeline update): Agent Orchestrator (update pipeline, exclude Owner Resolver) + App Builder (frontend wiring)
- G5 (repo cloning): Agent Orchestrator (workspace directory manager extension) + App Builder (settings UI for repo URL + token)
- G6 (remediation agent): Agent Orchestrator (new agent definition + execution flow)
- G7 (PR creation): Agent Orchestrator (git push + `gh pr create` integration)
- G8 (status flow): Agent Orchestrator (backend transitions) + App Builder (frontend badges + PR link)
- G9 (Docker): App Builder (packaging)
- G10 (error handling): App Builder (frontend)

## Implementation priority

The gaps should be addressed in this order, because each builds on the previous:

1. **G9: Docker first-run** — Without this, you can't even start the app cleanly
2. **G5: Repo cloning into workspace** — Foundation for remediation. Must work before agents can fix code
3. **G1 + G2: Import UX + Onboarding** — Without findings, nothing else matters. Onboarding now includes repo setup
4. **G4: Suggest-next guidance + pipeline update** — Updated pipeline (no Owner Resolver), wired to frontend
5. **G6: Remediation agent** — The hero feature. Agent writes code fixes guided by the planner
6. **G7: PR creation** — Agent pushes and creates draft PR. Completes the end-to-end loop
7. **G8: Status flow** — Makes progress visible (including "PR created" state)
8. **G3: Structured result cards** — Makes agent output trustworthy and scannable
9. **G10: Error handling** — Prevents session-ending frustration

## Resolved questions

- [x] **Scanner format:** Snyk free tier JSON export. Primary test target. LLM normalizer handles other formats too.
- [x] **Import button placement:** Permanent in the toolbar. Always available. Empty state also features it prominently.
- [x] **Result cards UX:** Structured cards in chat (compact). Sidebar as persistent reference (full detail). Chat = story, sidebar = truth.
- [x] **Batch mode:** One-at-a-time for MVP. Batch is a post-MVP feature for future customers.
- [x] **Owner Resolver:** Excluded from MVP pipeline. Maintainer is the owner. Bring back for enterprise persona.
- [x] **Definition of done:** Not "plan exported" but "PR created on GitHub, ready for human review and merge."
- [x] **Repo access:** Clone via GitHub URL into workspace directory. Requires personal access token in settings.
- [x] **Agent autonomy:** Propose draft PR, human reviews and merges. Agent never auto-merges.
- [x] **Commit message snippet:** No longer a separate export feature — the agent writes the commit message as part of the fix.
- [x] **Repo URL scope:** Global default in settings, with per-finding override possible in the future. For dogfooding, one repo is enough.
- [x] **Complex fixes:** Best-effort. Agent starts with a plan that the user approves, then executes. If the user isn't happy, they can chat to guide the agent — just like Claude Code. The workspace chat is collaborative, not fire-and-forget.
- [x] **Test suite scope:** Run the full test suite by default. Agent can ask the user if they want to skip or narrow the test run.
- [x] **Dry run mode:** Not needed. The draft PR itself is the trust mechanism — user reviews the diff on GitHub before merging. No extra "preview" step required.

## Open questions

All resolved. No remaining blockers for CEO approval.

---

_This PRD follows the Cliff product workflow. After CEO approval, it moves to the UX team for mockup creation via `/ux-designer`, then to `/architect` for implementation planning._
