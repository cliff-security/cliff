# Q01R Wave 2 — verification plan

**Goal:** Re-run the same UI-only QA that found B22–B30. Each bug must be gone. Drive at least one Critical through the full pipeline to a real PR. Verify dashboard grade moves toward A.

**Env:**
- Docker image `opensec:wave2` built from main @ 71ce1d7 (all 4 Q01R PRs merged)
- Container on port 8088, fresh `opensec-wave2-data` volume, fresh credential key
- No provider env vars (forces real BYOK flow)
- Target: cliff-security/NodeGoat (master branch)
- Driver: Claude in Chrome — UI only, opensec CLI forbidden

**App perms confirmed (Q5):** Contents:write, Pull requests:write, Metadata:read (✓). Missing Actions:read + Administration:read — only needed for the deferred autofix posture-checks; OK for this wave.

## Per-bug verification matrix

| Bug | Recreate steps | Expected (post-fix) |
|---|---|---|
| **B22** | Onboarding step 2 → "Connect with OpenRouter" → authorize → switch back to Cliff tab WITHOUT manual reload | Within ~2s of returning, UI flips to "Connected to OpenRouter" automatically (focus-refetch hook works) |
| **B23** | Connect cliff-security/NodeGoat (default branch: master) → assessment runs → inspect docker logs for `/branches/main` or `/commits?sha=main` | No `/main` requests in logs; calls hit `/master/protection` etc. Posture checks for branch_protection don't false-fail |
| **B24** | Dashboard "Level up to D" card → look at Auto-fix offerings → click | Auto-fix surface shows at most 2 checks (security_md, dependabot_config); clicking either succeeds (no 422). If we force a 422, inline error renders on the card |
| **B25** | Dashboard → click "Start" on Critical card → URL becomes `/issues?...&severity=critical&open=<fid>` | Severity dropdown reads "Crit" on initial render; only Critical rows shown; "Filtered · 3 of 45" |
| **B26** | Issues page with Todo > 0 | "Manual review queue is clear" (renamed) NOT shown when Todo has items |
| **B27** | Dashboard "Close the 3 open Criticals" → click Start | Navigates AND auto-opens side panel for first Critical finding (deep link via `?open=<fid>`) |
| **B28** | Click Start on a Critical → wait ~60s for plan agents to complete | Side panel top widget transitions from "Thinking…" to "Plan ready" within ~5s; activity log refreshes without panel re-open |
| **B29** | After plan stage completes | Footer button "Approve & generate fix" appears; clicking it calls `/plan/approve` then triggers executor (verify `sidebar.plan.approved=true`) |
| **B30** | After approve+execute | Executor preflight runs `GET /repos/cliff-security/NodeGoat` — since app perms now allow push, preflight returns can_push=true; executor pushes branch and creates real PR; UI shows PR link in side panel |

## Exit criteria

- All 9 bugs gone (none of the "Recreate" steps reproduce the broken state)
- Onboarding ⩽ 3 clicks per screen, ⩽ 5 minutes end-to-end
- At least one Critical finding drives through to a real PR on cliff-security/NodeGoat — confirming the full happy path works UI-only
- Dashboard reflects the closed finding within 1 assessment cycle
- Grade does not regress (F → D ideally, but no regression is the must)

## Out of scope (Wave 2)

- Re-rebasing the 11 wave-1 conflicting PRs (they were closed; the executor in Wave 2 may surface fresh PRs naturally as we trigger more remediations)
- The two missing GitHub App permissions (Actions:read, Administration:read) — those gate the deferred autofix posture-checks that aren't in this build
- Installation-token rearchitecture (per ADR-0037 alternatives — deferred)
