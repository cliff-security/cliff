# IMPL-0002 · Execution playbook

**Companion to:** `IMPL-0002-earn-the-badge.md`
**Audience:** You (CEO) + every Claude Code session working on Earn the Badge
**Goal:** Ship IMPL-0002 efficiently, in parallel, with a visible demo path from day 1

---

## The three execution principles

1. **Shell first, fill in second.** Build a clickable end-to-end UI wired to fake data *before* any real backend work. The CEO can eyeball the whole journey on day 1. Every subsequent PR replaces one fake with something real.
2. **Parallelize by worktree, serialize by seam.** Use git worktrees so three sessions can work concurrently. The only serialization points are: database migration (A1), the V1↔V2 interface (locked in code on day 1), and the seed fixture repo.
3. **Every PR must be visually demoable.** A screenshot or 10-second Loom/asciinema goes in the PR description. If it cannot be demoed, it is either too big (split it) or pure infrastructure (pair it with a visible follow-up).

---

## Day 0 · Setup (one session, ~30 min)

Before any feature work, land these in one small PR on `main` (`feat/earn-the-badge-scaffold`):

1. **Seed fixture repo.** Check in `fixtures/demo-repo-alex/` — a minimal Node project with:
   - A `package.json` + `package-lock.json` pinned to `braces@3.0.2`, `lodash@4.17.20`, `minimatch@3.0.4` (the exact packages used in UX-0002 mockups). These produce real findings.
   - No `SECURITY.md`, no `.github/dependabot.yml` (so posture checks fail).
   - A `README.md` so the badge installer has something to edit.
2. **Feature flag.** Add `CLIFF_EARN_THE_BADGE_ENABLED=false` in `config.py`. Every new route and UI surface is gated on it. The main app ships normally; you test the new flow by setting the flag locally.
3. **API contracts as stubs.** Add empty route files `onboarding.py`, `assessment.py`, `posture.py`, `badge.py`, `dashboard.py` that return hardcoded fixture JSON matching the shapes in IMPL-0002 §D. These unblock the frontend team on day 1.
4. **Worktrees.** Create three workspace directories:
   ```
   ~/projects/Cliff                 # main worktree, for PR reviews
   ~/projects/Cliff-v1-agents       # branch earn/v1-agents
   ~/projects/Cliff-v2-backend      # branch earn/v2-backend
   ~/projects/Cliff-v2-frontend     # branch earn/v2-frontend
   ```
   Command:
   ```bash
   cd ~/projects/Cliff
   git worktree add ../Cliff-v1-agents -b earn/v1-agents
   git worktree add ../Cliff-v2-backend -b earn/v2-backend
   git worktree add ../Cliff-v2-frontend -b earn/v2-frontend
   ```
5. **Three Claude Code sessions.** Open one session per worktree:
   - **Session A — V1 agents** (worktree `Cliff-v1-agents`). Owns Milestone C1 + E1–E4. Invoked as `/cliff-agent-orchestrator`.
   - **Session B — V2 backend** (worktree `Cliff-v2-backend`). Owns A, B, C2, D. Invoked as `/app-builder`.
   - **Session C — V2 frontend** (worktree `Cliff-v2-frontend`). Owns F, G, H. Invoked as `/app-builder`.

After the Day 0 PR merges, all three sessions run to the next wave **in parallel**.

---

## Wave plan

Each wave produces 1–3 PRs. A wave is done when every PR in it merges. Review cadence: you review in the morning and evening. Each session parks on the next wave while you sleep.

### Wave 1 · "Clickable shell" (1 day)

Goal: by end of wave, `scripts/dev.sh` boots into an onboarding welcome page, you can walk through all three steps with fake validation, and the dashboard renders UX-0002 frame 2.2 with hardcoded data.

| PR | Owner | Ships |
|---|---|---|
| `feat/earn-scaffold-data` | Session B | Seed fixture repo + feature flag + stub route bodies returning fixture JSON (no logic yet) |
| `feat/earn-onboarding-ui` | Session C | Frames 1.0, 1.1, 1.1a, 1.4, 1.5 wired to stub routes. Frame 1.2 (error) and 1.3 (verified) on a toggle |
| `feat/earn-dashboard-shell` | Session C | Frame 2.2 (Dashboard) + 3.1 row shape with plain-language **dummy** strings, behind the feature flag |

**Visual validation at end of Wave 1:**
- `CLIFF_EARN_THE_BADGE_ENABLED=true scripts/dev.sh` → browser → walk Welcome → Connect (anything validates) → AI → Start → Dashboard
- Every screen from the UX gallery renders against fake data. You can click every button.
- Take a 30-second screen recording; if the flow feels off, we fix the UX now while the cost is low.

### Wave 2 · "Real assessment" (2–3 days)

Now we replace the fake data with a real assessment.

| PR | Owner | Ships |
|---|---|---|
| `feat/earn-db-migration` | Session B | Milestone A1 + A2 · migration, models, DAOs, migration test. **Blocks everything downstream.** |
| `feat/earn-parsers-npm` | Session B | Milestone B1 · npm parser + registry + fixtures |
| `feat/earn-parsers-pip-go` | Session B | Milestone B2 + B3 · pip + go parsers |
| `feat/earn-osv-client` | Session B | Milestone B4 · OSV.dev + GHSA clients with retry/cache |
| `feat/earn-posture-module` | Session B | Milestone B5 · posture checks (branch protection, secrets, files) against a mocked `GithubClient` |
| `feat/earn-normalizer-plain` | Session A | Milestone C1 · normalizer prompt extension + evaluation fixture |

**These five PRs can land in any order** — the migration PR goes first; the other four are independent.

**Visual validation at end of Wave 2:**
- `pytest tests/test_assessment/` green (unit).
- `pytest tests/e2e/test_assessment_e2e.py -k demo_repo` runs an assessment against `fixtures/demo-repo-alex/` and you see 3 findings in the SQLite DB. Open the DB with `sqlite3 data/cliff.db "select id, plain_description from findings"` — each row has a plain-English sentence.

### Wave 3 · "Real end-to-end" (2 days)

| PR | Owner | Ships |
|---|---|---|
| `feat/earn-assessment-orchestrator` | Session B | Milestone B6 · wires parsers + OSV + posture + normalizer through `engine.py`, writes `assessments` + `posture_checks` rows |
| `feat/earn-routes-onboarding-assessment` | Session B | Milestone D1 + D2 · real `/api/onboarding/*` and `/api/assessment/*` replacing stubs. Frontend keeps working (same shapes) |
| `feat/earn-routes-dashboard-posture-badge` | Session B | Milestone D3 + D4 · dashboard aggregator + posture/badge triggers |
| `feat/earn-v1-workspace-kind` | Session A | Milestone E4 · `WorkspaceKind` enum + cleanup trigger |

**Visual validation at end of Wave 3:**
- Onboarding against `fixtures/demo-repo-alex/` → real assessment runs → real findings land → Dashboard shows them.
- You are now looking at a real assessment of a real repo, end to end.

### Wave 4 · "PRs and celebration" (2 days)

| PR | Owner | Ships |
|---|---|---|
| `feat/earn-agent-security-md` | Session A | E1 · SECURITY.md generator agent + template render test |
| `feat/earn-agent-dependabot` | Session A | E2 · dependabot config generator agent |
| `feat/earn-agent-badge-installer` | Session A | E3 · badge installer agent |
| `feat/earn-frontend-posture-actions` | Session C | G5 · posture check item with "Generate and open PR" action wired to the agent triggers |
| `feat/earn-frontend-celebration` | Session C | H1 + H2 + H3 · shield SVG + earn celebration + add-to-README dialog |
| `feat/earn-frontend-freshness` | Session C | H4 · freshness card + re-assess diff |

**Visual validation at end of Wave 4:**
- Click "Generate and open PR" on SECURITY.md → watch a real draft PR land on GitHub on a test repo you own.
- Solve the three findings from the demo repo → badge criteria flip green one by one.
- Last criterion passes → you see the confetti celebration. Click "Add badge to README" → real draft PR on GitHub with the badge markdown.

### Wave 5 · "Polish + prove" (1 day)

| PR | Owner | Ships |
|---|---|---|
| `feat/earn-e2e-playwright` | Session C | I1 · end-to-end Playwright walk-through against the demo repo |
| `docs/earn-assessment-engine-guide` | Session B | I2 · contributor guide |
| `feat/earn-flag-on-default` | any | Flip `CLIFF_EARN_THE_BADGE_ENABLED=true` in the default config. Remove the flag in a later cleanup PR after soak. |

---

## "See it with your eyes" — validation checklist

Every PR description must include one of:

- **UI change** → before/after screenshot taken from Chrome (localhost:5173), at the same viewport.
- **Backend change** → a 5-line snippet of `curl` or `sqlite3` output showing the new behavior.
- **Agent change** → the relevant excerpt from `backend/data/workspaces/<id>/agent-run.log` showing the new output.

For the Waves above, the full "can I see it work?" journey is:

| After Wave | What you physically do | What you should see |
|---|---|---|
| 1 | `scripts/dev.sh`, open `localhost:5173` | Walk the whole UX gallery end-to-end with fake data |
| 2 | `pytest backend/tests/test_assessment/` + open `data/cliff.db` | Real assessment rows + real plain-language strings |
| 3 | Onboarding flow in the browser against `fixtures/demo-repo-alex/` | Real grade C, real 3 findings on Dashboard |
| 4 | Click "Generate and open PR" on SECURITY.md against a real test repo (e.g. `galanko/cliff-demo`) | A draft PR appears on GitHub |
| 5 | `npm run test:e2e` | Playwright walks the full journey, green |

---

## Guardrails for the Claude Code sessions

The three sessions should each start by reading:

1. `CLAUDE.md` (project conventions, Git Workflow rules)
2. `docs/architecture/plans/IMPL-0002-earn-the-badge.md`
3. This file
4. Their vertical's existing code (Session A: `backend/cliff/agents/`, `backend/cliff/workspace/`; Session B: `backend/cliff/api/routes/`, `backend/cliff/db/`; Session C: `frontend/src/`)

Each session follows the PR rules from `CLAUDE.md`:

- Never commit to `main`, never force-push to `main`, never merge its own PR.
- Conventional commits, one feature per branch, stacked PRs avoided.
- Tests written **first**, feature code second.
- If the session finishes a wave before the others, it picks up the next wave's PR **that does not depend on an unmerged wave PR**. The dependency rules are the table rows in Wave sections above.

When a session is blocked waiting on a merge:

- It should open a draft PR anyway so the CEO can pre-review.
- It moves on to the next independently mergeable task in its queue.

---

## PR sizing rule

Soft target: **300 lines changed per PR** (excluding fixtures and migrations). Hard limit: **600 lines**. If a task exceeds that, the session splits it and says so in the PR description.

Rationale: you are the only reviewer. Small PRs merge in 5 minutes of review; big PRs eat a morning. Five merges a day beats one merge a day, every day.

---

## When things drift

- If a session introduces a change that touches another vertical's files, `/architect` rejects the PR (see architect review checklist).
- If a feature works but doesn't match the UX spec, `/ux-designer` reviews the PR screenshot and flags drift before merge.
- If test coverage drops, `/architect` rejects.
- If three consecutive PRs from one session have ruff/lint failures in CI, that session pauses and invokes `/engineering:code-review` on its own changes.

---

## Success definition

IMPL-0002 is done when:

- Alex (the persona) can run `docker run cliff`, go through onboarding against their real repo, see a real grade, solve real findings, and end up with a real "Secured by Cliff" badge on their README.
- You have watched this happen, end to end, on your own eyes against `fixtures/demo-repo-alex/` and then against one real external repo.
- The E2E Playwright test is green in CI.
- `CLIFF_EARN_THE_BADGE_ENABLED` is on by default.
