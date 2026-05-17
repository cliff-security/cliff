# QA-0001 / Q01R Wave 2 — re-run verification on the fully-merged Wave 1.5 build

**Date:** 2026-05-17
**Driver:** Claude in Chrome — UI only, `opensec` CLI forbidden
**Target:** cliff-security/NodeGoat (master branch)
**Environment:**
- Docker image `opensec:wave2` built from `main @ 71ce1d7` (all 4 Q01R PRs merged: #167, #170, #168, #169)
- Container on port 8000 (matches App's hardcoded setup URL — sidesteps B33 for the QA itself)
- Fresh `opensec-wave2-data` volume + fresh credential key (standard base64, working around B31)
- No provider env vars (forces real BYOK flow)
- Provider: OpenRouter OAuth → `openrouter/anthropic/claude-haiku-4.5`
- GitHub: galanko, device-flow OAuth, installation 133175235

## Verdict: AMBER

Wave 1.5 fixes hold at the UI layer (all 9 bugs surface their intended behavior). But the fresh-Docker happy path is still blocked by a new layer of bugs upstream, AND the most important Wave 1.5 fix (B30 — actual PR creation) is only partially functional: the UI surfaces the failure correctly with a "How to fix" link, but the executor still goes through 4+ minutes of work before push fails — meaning the preflight isn't gating, and the user-OAuth token from the device flow doesn't actually have push perms despite the App declaring them and the user being admin.

## Wave 1.5 fix verification matrix

| Bug | Fix surface | Verified? | Notes |
|---|---|---|---|
| **B22** | `useOpenRouterPolling` focus refetch | ✅ | User reported OAuth onboarding "worked perfectly", no manual reload |
| **B23** | Default-branch resolution | ✅ | Dashboard says "ran ... 2d564bb on **master**"; no `/branches/main` 403s |
| **B24** | Shrunk `_AUTO_FIXABLE_CHECKS` + 4xx surface | ✅ (negative) | Dashboard posture card shows "Start" — no broken auto-fix promise |
| **B25** | URL → severityFilter hydration | ✅ | `/issues?severity=critical` correctly hydrates dropdown + count |
| **B26** | Empty-review-card visibility | ✅ | No false green check when Todo has items |
| **B27** | Gate cards deep-link with `?open=<fid>` | ✅ | Dashboard Start → side panel auto-opens for first matching Critical |
| **B28** | `useAgentRuns` always polls 2s/5s | ✅ | Side panel transitioned Planning → Plan ready without refresh |
| **B29** | DefaultFooter approve-then-execute | ✅ | Three buttons (Approve A / Refine R / Reject X) appeared on plan_ready |
| **B30** | Preflight + error_details rendering | 🟡 PARTIAL | UI ✅ (error card + "How to fix" link render). Backend ❌ (preflight didn't gate; push still fails) |

## New defects found (Q01R-W2)

Per-bug details: `evidence/Q01R-W2/B31-*.md` through `B35-*.md`.

| ID | Sev | Surface | Headline |
|---|---|---|---|
| **B31** | P0 | backend (vault) | Vault rejects URL-safe base64 keys silently → 503 on credential routes |
| **B32** | P1 | backend (lifespan) | Vault init exception swallowed by bare `except` with misleading warning |
| **B33** | P0 | App config + backend | GitHub App `setup_url` hardcoded to `localhost:8000`; non-default-port deploys break |
| **B34** | P2 | flaky | Device-flow Authorize click was flaky; eventually worked. Needs more data before classifying |
| **B35** | P1 | backend (preflight) + UI (header) | Executor preflight didn't gate; UI top widget stuck on "Pushing branch" past terminal error; push token still lacks write |

## What still blocks the "ship a real PR end-to-end via UI only" promise

1. **B35a/c** — executor invokes successfully but can't push. No PR was ever created end-to-end via UI in this run.
2. **B33** — fresh-Docker users on non-default ports get the App setup callback sent to the wrong instance.
3. **B31** — fresh-Docker users using the natural Python `secrets.token_urlsafe(32)` for the vault key get silent 503s.

## What worked (keep these)

- Onboarding ≤ 5 clicks per screen when prerequisites are right
- Plan-stage agent quality remains high (95% confidence dependency-bump recommendations)
- Side panel polls cleanly through plan stage and surfaces approve actions on time
- Error rendering with "How to fix" link is genuinely useful UX
- Dashboard "Level up to D" panel correctly enumerates only what works (no fake auto-fix promises post-B24)

## Recommendation

Wave 3: parallel-fixable IMPL plans following the Wave 1.5 pattern.

- **W3-A — vault key UX + error visibility (B31 + B32)** — backend, tiny
- **W3-B — GitHub App callback flexibility (B33)** — App config + backend recovery flow, medium
- **W3-C — executor preflight + UI terminal-error reactivity (B35a + B35b)** — backend wiring + frontend state, medium
- **W3-D — post-install push-access diagnostic (B35c)** — backend, small

Architect to draft IMPLs + ADR amendment to ADR-0037; R&D ships 3-4 PRs in parallel; re-run Wave 3 QA after merge. Target: a single Critical finding drives F → D end-to-end via UI alone.
