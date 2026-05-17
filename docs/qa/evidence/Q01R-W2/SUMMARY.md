# Q01R Wave 2 — final verdict

**Date:** 2026-05-17
**Env:** opensec:wave2 from `main @ 71ce1d7` (all 4 Q01R PRs merged); container on port 8000 (matches App's hardcoded setup URL); fresh DB
**Driver:** Claude in Chrome — UI only
**Target:** cliff-security/NodeGoat (master branch)
**Provider:** OpenRouter OAuth → `openrouter/anthropic/claude-haiku-4.5`
**GitHub:** galanko, device-flow OAuth, install 133175235

## Verdict

**AMBER.** The Wave 1.5 fixes hold at the UI layer (all 9 bugs surface their intended behavior). But the fresh-Docker happy path is still blocked by a layer of new bugs upstream of where the Wave 1.5 fixes sit, AND the most important Wave 1.5 fix (B30 — actual PR creation) is only partially functional: the UI correctly surfaces the failure with a "How to fix" link, but the executor itself can still go through 4+ minutes of work before the push fails — meaning the preflight isn't gating, and the user-OAuth token from the device flow doesn't actually have push perms despite the App declaring them.

## Wave 1.5 bug fixes — verification matrix

| Bug | Fix lives in | Verified now? | Notes |
|---|---|---|---|
| B22 | `useOpenRouterPolling` focus refetch | ✅ verified | User reported OAuth onboarding "worked perfectly", no manual reload needed |
| B23 | `branch=` resolved from `/repos/{owner}/{repo}` | ✅ verified | Dashboard says "ran ... 2d564bb on **master**", no `/branches/main` 403s |
| B24 | Shrunk `_AUTO_FIXABLE_CHECKS` + 4xx surface | ✅ verified (negative) | Dashboard's posture card shows just "Start" — no broken "Auto-fix N of N" |
| B25 | URL → severityFilter hydration | ✅ verified | `/issues?severity=critical` correctly shows "Crit" dropdown + filtered count |
| B26 | Empty-review-card visibility | ✅ verified | No false green check when Todo has items |
| B27 | Gate cards deep-link with `?open=<fid>` | ✅ verified | Dashboard Start → side panel auto-opens for first Critical |
| B28 | useAgentRuns always polls 2s/5s | ✅ verified | Side panel transitioned Planning → Plan ready without manual refresh |
| B29 | DefaultFooter approve-then-execute chain | ✅ verified | "Approve & generate fix (A)" / Refine (R) / Reject (X) buttons appeared on plan_ready and fired correctly |
| B30 | Preflight + error_details rendering | 🟡 PARTIAL | UI side ✅ (error card + "How to fix" link render correctly). Backend side ❌ (preflight didn't gate; actual push still fails) |

## New defects found (Q01R-W2)

| ID | Sev | Surface | Status |
|---|---|---|---|
| B31 | P0 | Vault rejects URL-safe base64 keys silently → 503 on credential routes | New — needs fix |
| B32 | P1 | Vault init exception swallowed with misleading "set OPENSEC_CREDENTIAL_KEY" warning | New — needs fix |
| B33 | P0 | GitHub App `setup_url` hardcoded to `localhost:8000`; breaks any non-default-port deploy | New — needs fix (App config + UI recovery) |
| B34 | P0→P2 | Device-flow `Authorize` click had to be retried (originally appeared to be GitHub-side; eventually worked) | Downgraded — flaky, needs more data |
| B35 | P1 | Executor preflight didn't gate; UI top widget stuck on "Pushing branch" past terminal error; push token still lacks write despite Q5 + ADR-0037 | New — needs fix (3 layers) |

## What works (carry into Wave 3)

- Onboarding is < 5 clicks per screen when the prerequisites are right
- Plan-stage agent quality remains high (95%-confidence dependency-bump recommendations)
- Side panel polls cleanly through plan stage and surfaces approve actions on time
- Error rendering with "How to fix" link is genuinely useful UX

## What blocks the "ship a real PR end-to-end via UI only" promise

1. **B35a/c** — executor invokes successfully but can't push. No PR ever created end-to-end via UI in this run.
2. **B33** — fresh-Docker users on non-default ports get the App setup callback sent to the wrong instance
3. **B31** — fresh-Docker users using the natural Python `secrets.token_urlsafe(32)` for the vault key get silent 503s

## Recommendation

Spawn another /architect → 3-4 IMPL plans → parallel fix wave following the same Wave 1.5 pattern. Specifically:

- **W2-A (vault + onboarding ops)** — B31 + B32 (small): URL-safe-base64 acceptance + exc_info on vault init
- **W2-B (GitHub App callback)** — B33 (medium): support per-deploy setup URL, OR add a manual paste recovery
- **W2-C (executor preflight wiring + top-widget reactivity)** — B35a + B35b (medium): wire the preflight into ALL executor invocations, and make the side panel header reflect terminal-error state
- **W2-D (post-install perm verification)** — B35c (small): on every executor trigger AND on Settings page load, call `check_repo_push_access` and surface a clear "your App install needs an admin to approve the new permissions" message when push is denied

After those land, re-run Wave 3 QA. Target: a single Critical finding driving to a real merged PR with the dashboard grade moving F → D.

## Evidence files
- `B31-vault-urlsafe-base64.md`
- `B32-vault-error-swallowed.md`
- `B33-github-app-setup-url-hardcoded.md`
- `B34-device-code-rejected.md`
- `B35-preflight-not-gating-and-stale-top-widget.md`
- `PLAN.md` (verification matrix)
- `VERIFICATIONS-IN-PROGRESS.md` (live notes)
