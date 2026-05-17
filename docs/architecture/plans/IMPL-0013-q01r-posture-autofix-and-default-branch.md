# IMPL-0013: Q01R — Posture autofix contract + default-branch resolution

**Scope:** Wave 1.5 (Q01R) bug fixes — posture/assessment cluster
**Bugs:** B23, B24
**Owner:** App Builder (V2) — backend `assessment/` + `api/routes/`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

Two posture-engine bugs blocking new-user happy path:

- **B24 (P0)** — Dashboard advertises "Auto-fix 2 of 5" for `branch_protection`, `actions_pinned_to_sha`, `stale_collaborators`, `code_owners_exists`. Backend `POST /api/posture/fix/{check_name}` only accepts `security_md` and `dependabot_config` → returns 422 → frontend swallows error silently. The dashboard is offering things that physically can't be fixed (no agent template, no `WorkspaceKind` value).
- **B23 (P1)** — Posture engine hardcodes `branch="main"` in `RepoCoords`; calls `/branches/main/protection` and `/commits?sha=main` on every repo. Returns 403/404 on `master`-default repos (every NodeGoat-vintage codebase) and produces falsely-failing posture rows.

Per the architect's "delete before adding" principle, **B24's simplest correct fix is to shrink `_AUTO_FIXABLE_CHECKS` from 4 to 2 to match what the backend actually supports.** Building two new agent templates this wave is over-scoped — track that as follow-up. We also harden the 4xx surface so this class of contract drift never silently breaks the UI again.

**B23's fix is a 3-line change** to compute the default branch from `GET /repos/{owner}/{repo}` once per assessment and thread it through `RepoCoords`.

## Root causes (grounded in code)

| Bug | File:line | Issue | Required change |
|---|---|---|---|
| B24a | `backend/cliff/api/routes/posture.py:33` | `PostureFixCheckName = Literal["security_md", "dependabot_config"]` | No change (the enum is correctly narrow — fix is upstream in level-up) |
| B24b | `backend/cliff/api/routes/_level_up.py:87–92` | `_AUTO_FIXABLE_CHECKS = (security_md, dependabot_config, code_owners_exists, actions_pinned_to_sha)` — last two have no handler | **Shrink** to `(security_md, dependabot_config)` until handlers + agent templates land |
| B24c | `frontend/src/components/dashboard/GateRow.tsx` (Auto-fix button) | onClick uses TanStack mutation that doesn't surface server errors | Add toast on `onError` (Sonner is already installed); show inline error text on the card when the most recent attempt 4xx'd |
| B23 | `backend/cliff/assessment/posture/__init__.py:221` | `RepoCoords.branch: str = "main"` default | Remove default; require caller to pass `default_branch`. Caller resolves it via `GET /repos/{owner}/{repo}` → `default_branch` field, then passes to `run_all_posture_checks()` |

## Files touched

Backend (V2 — `api/routes/`, `assessment/`):
- `backend/cliff/api/routes/_level_up.py` — `_AUTO_FIXABLE_CHECKS` → 2 entries
- `backend/cliff/assessment/posture/__init__.py` — `RepoCoords.branch` no default; `run_all_posture_checks` accepts `default_branch` arg
- `backend/cliff/assessment/posture/github_client.py` — confirm all callers pass `branch` (no remaining literal "main")
- `backend/cliff/assessment/runner.py` (or wherever the posture run is kicked off) — fetch repo metadata, pass default branch

Frontend (V2 — `components/`):
- `frontend/src/components/dashboard/GateRow.tsx` — Auto-fix button: `onError` → toast + inline error
- `frontend/src/api/hooks.ts` (or wherever the posture-fix mutation lives) — return useful error messages from 422 bodies

No new agent templates / WorkspaceKind values this wave. Tracking the two missing fixes as separate BACKLOG items (see end).

## Test plan (TDD-first)

Unit (backend, pytest):
- `test_routes_level_up.py` — `_AUTO_FIXABLE_CHECKS` contains only `security_md` and `dependabot_config`; dashboard payload's `auto_fixable_check_names` reflects this
- `test_routes_posture.py` (existing) — already covers the 2 valid check names; add explicit 422 assertion for `code_owners_exists` and `actions_pinned_to_sha` so the contract is locked
- `test_assessment_posture.py` (new or extended) — `run_all_posture_checks` called with `default_branch="master"` queries `/branches/master/protection` and `/commits?sha=master`; injecting `"main"` queries `/main`
- `test_assessment_runner.py` (extended) — runner reads `default_branch` from `/repos/{owner}/{repo}` (mock GitHub API)

Unit (frontend, Vitest):
- `GateRow.test.tsx` — when posture-fix mutation rejects with 422, toast is called and inline error renders on the card
- `useAutoFixPosture.test.ts` (or wherever the mutation lives) — 422 body parsed into a useful message ("This check isn't auto-fixable yet")

E2E (manual, captured by Wave-2 Q01 re-run):
- Connect cliff-security/NodeGoat (master), run assessment, posture sub-page shows `branch_protection` and recent-commits checks ran (not 403/404)
- Dashboard "Level up" card shows at most 2 auto-fix entries
- Clicking "Auto-fix" on the supported ones spawns the workspace and proceeds (existing behavior); UI never silently fails on a 4xx

## Risks

- **Shrinking `_AUTO_FIXABLE_CHECKS` reduces the dashboard's prominent action surface for first-time users.** Mitigation: dashboard already shows "Close the 3 open Criticals" etc. — the auto-fix is one of many actions. And it's better to under-promise than dead-button.
- **`default_branch` query is an extra GitHub API call per assessment.** Mitigation: cheap (one round-trip) and cacheable per repo per assessment. Token rate budget is not a concern.
- **`RepoCoords.branch` losing its default is an API break for any internal caller passing partial args.** Mitigation: full grep + tests; only one production caller path exists today.

## Follow-up BACKLOG items (separate work, not this wave)

- **Agent template + `WorkspaceKind` for `code_owners_exists`** — generate a `.github/CODEOWNERS` PR. Mirror `security_md_generator.md.j2` shape
- **Agent template + `WorkspaceKind` for `actions_pinned_to_sha`** — bulk-rewrite workflow files to pin to SHAs; this one is genuinely harder because the agent has to resolve current SHAs for each action — defer until a maintainer asks for it
- Once each lands, re-expand `_AUTO_FIXABLE_CHECKS` accordingly. Test ensures the registry, route enum, and `_CHECK_TO_WORKSPACE_KIND` stay in lockstep

## Rollout

Single PR, conventional commit prefix `fix(q01r-posture):`. Two commits, in this order:
1. B24 (shrink registry + frontend toast)
2. B23 (default branch resolution)

Target branch: `main`.
