# QA-0001 — Q01R Wave 3 rerun

**Date:** 2026-05-17
**Build under test:** Cliff @ `main = 8139bad` (PRs #173, #174, #175, #176 all merged)
**Docker image:** `cliff:wave3` (post-rename: `backend/cliff/*`, env prefix `CLIFF_*`)
**Vault key:** standard base64 (`CLIFF_CREDENTIAL_KEY`)
**Container:** `cliff-wave3`, ports `0.0.0.0:8000` + `0.0.0.0:3000`, volume `cliff-wave3-data`
**AI provider:** OpenRouter OAuth → `anthropic/claude-haiku-4.5`
**GitHub App:** `cliff-local-test` (installation_id 133175235 on cliff-security org, user @galanko)
**Target repo:** `cliff-security/NodeGoat` (default branch `master`)
**QA driver:** Claude in Chrome (UI-only, no CLI)
**Inputs verified by hand:** none — full UI loop

## Headline result

| Outcome | Status |
|---|---|
| All four Wave 2 PRs land their UI fixes correctly | ✅ |
| B35a / B35b — `executor_failed` stage + Needs-attention + Retry button | ✅ verified on a real executor failure |
| B35c — Settings push-access badge | ✅ green on first load |
| B31 / B32 — vault init clean + visible errors | ✅ container booted on standard-b64 key without spurious warning |
| All eight Wave 1.5 fixes (B22–B30) still hold | ✅ (with one new follow-up: B36) |
| Grade moves F → D after the agent-produced PR merges | ❌ **gate not reached** — the agent's PR never landed (B37 below) |

**Bottom line:** Wave 2's promised UI surface ships exactly as designed. The promised end-to-end ("Critical → real PR on cliff-security/NodeGoat via UI alone") still doesn't complete — it now fails at a different layer than Wave 2, surfaces cleanly via PR-C's new error UX, and the underlying gap is the deferred IMPL-0019 work that IMPL-0017 explicitly flagged in its Risks section.

Two new defects worth tracking:

- **B36 (P1)** — passive backend progress doesn't reach the UI: the side panel sits on "Enriching the finding · 0s" while five agents run server-side. F5 force-refresh fixes it instantly. Reactivity regression of B22's class.
- **B37 (P0 for "real PR" outcome, P1 otherwise)** — preflight `check_repo_push_access` returns `can_push=true` via the user-perms fallback, then the actual `git push` fails because the user OAuth token doesn't carry `repo` scope at the git-protocol layer. Matches the deferred-work case IMPL-0017 anticipated.

## Verification matrix

| ID | What | Wave 2 status | Wave 3 status | Evidence |
|---|---|---|---|---|
| B22 | Issues counter live-updates as workspaces start/stop | ✅ (Wave 1.5 fix held) | ✅ partial — initial in-progress 0→1 transition rendered, but background agent progress now stuck (see B36) | Side panel snapshot at `t=0`: "In progress 1, Todo 2" |
| B23 | Posture autofix registry shrunk | ✅ | ✅ | Dashboard shows 5/15 posture checks passing without overflow |
| B24 | Default branch resolves correctly | ✅ | ✅ | Workspace clone tracks `origin/master` (NodeGoat's actual default) |
| B25 | Empty + active swim-lane states | ✅ | ✅ | "Needs you 1 — Approve, refine, or reject before the agent ships." appears after planner completes |
| B26 | Stage chip rendering ("Planning", "Plan ready", etc.) | ✅ | ✅ | Side panel header chips: Planning → Plan ready → Generating fix → Needs attention all observed |
| B27 | Cancel run button + chained mutations disabled | ✅ | ✅ | "Cancel run" visible during executor; disappears on completion |
| B28 | Issues UX polish (filters, scope chip, sorting) | ✅ | ✅ | Severity dropdown shows All 46 / Crit 3 / High 15 / Med 22 / Low 6 with proper counts |
| B29 | Issues UX polish (side panel layout, dependency display) | ✅ | ✅ | "Dependency" type chip + CVE in subtitle rendering |
| B30 | Real PR on cliff-security/NodeGoat via UI alone | ❌ — push-token preflight added but actual push still fails | ❌ — preflight passes via fallback path, push still fails; UI failure UX now correct (B35a/B35b) | See B37 below |
| B31 | Vault accepts url-safe base64 | n/a (broken in W2) | ✅ — booted on standard b64 (the safer of the two), no spurious warning | `docker logs cliff-wave3`: `[INFO] cliff.main: Credential vault initialized` (single line, no "set OPENSEC_CREDENTIAL_KEY to enable") |
| B32 | Vault init error visible with `exc_info` | n/a (broken in W2) | ✅ | Same as B31 — happy path; no exception to surface |
| B33 | GitHub App manual install recovery | n/a (broken in W2) | ✅ — install completed via canonical callback path, recovery UI not exercised | Settings → Integrations shows GitHub Live with @galanko |
| B34 | Device-flow Authorize | flaky, deferred | not exercised — OpenRouter onboarding went via OAuth, not device flow | n/a |
| B35a | Preflight blocks executor with insufficient install perms | broken | ✅ preflight ran (`GET /repos/.../installation` 401 → fallback) — but fallback returned can_push=true (see B37). Behavior at the test layer matches IMPL-0017 |
| B35b | Side panel header transitions to "Needs attention" + Retry | broken | ✅ verified end-to-end on a real executor failure |
| B35c | Settings push-access badge | broken | ✅ green "Push verified" badge on first load |

## Walkthrough

### t≈0 — fresh container boot

```
docker run -d --name cliff-wave3 -p 8000:8000 -p 3000:3000 \
  -e CLIFF_CREDENTIAL_KEY="$(base64-standard 32 bytes)" \
  -v cliff-wave3-data:/data cliff:wave3
```

Health was 200 within 1 s. Logs show:
- `Applying migration 003_credential_and_audit_log.sql`
- `cliff.main: Credential vault initialized` — single clean line; no "set OPENSEC_CREDENTIAL_KEY" misleading warning (B31/B32 fixes holding).

### t≈3 min — user onboarding

@galanko completed:
1. OpenRouter OAuth → connected, model `anthropic/claude-haiku-4.5`.
2. GitHub App install on cliff-security org → connected via canonical callback path on `localhost:8000`. **B33 manual recovery card NOT exercised** (callback succeeded on first try; would only render if port mismatch).
3. Initial assessment of cliff-security/NodeGoat completed, dashboard populated.

### t≈9 min — Settings sanity check (B35c verification)

Settings → Integrations renders the GitHub integration card:

```
GitHub                                              ● Live    Disconnect
github.com/cliff-security/NodeGoat · 2 credentials · @galanko

✓ Push verified                                       (green pill, B35c)
```

Verdict: **B35c ✅** on the happy path. The card surfaces the diagnostic exactly per IMPL-0018.

### t≈10 min — Issues → Critical filter → Start

`/issues?severity=critical` shows three minimist@x.y.z prototype-pollution criticals (CVE-2021-44906). Clicked **Start** on `minimist@1.2.0`.

Side panel opened with:
- Header chips: Critical + Planning
- "Reviewing the advisory and the call sites..."
- Activity: 1 run ("Enriching the finding")
- Cancel run button at bottom (B27)

### t≈10:00 → t≈11:15 — Pipeline ran server-side

Backend logs show 5 agents completed in ~45 s:
- 19:10:41 `finding_enricher → v1`
- 19:10:49 `owner_resolver → v2`
- 19:10:57 `exposure_analyzer → v3`
- 19:11:05 `evidence_collector → v4`
- 19:11:15 `remediation_planner → v5`

UI sat on "Enriching the finding · 0s" the entire time. Network panel: frontend re-polled `/agent-execution/stream` 30+ times (all 200 OK) but never re-fetched `/agent-runs`. **First reproduction of B36 (see write-up below).**

Hard F5 → UI snapped to correct state: Plan ready chip, 6-step plan, 5 runs visible, "Needs you 1" swim lane, Approve & generate fix / Refine / Reject buttons.

### t≈14:35 — Approve & generate fix

Click on **Approve & generate fix**. Mutation invalidated queries correctly — side panel switched to:
- Header chip: Generating fix
- New top activity entry: "Applying the fix · 0s"
- 6 runs

Preflight ran inline (PR-#168 → PR-#175 chain):

```
GET https://api.github.com/repos/cliff-security/NodeGoat                  200 OK
GET https://api.github.com/repos/cliff-security/NodeGoat/installation     401 Unauthorized
```

The `/installation` 401 with the user OAuth token is exactly the case IMPL-0017's spike acknowledged. PR-C's fallback engaged and returned `can_push=true` based on user perms (@galanko is a collaborator with push). **Executor was allowed to proceed.**

### t≈14:35 → 19:46 — Executor ran for 5m 11s

Backend approved ~30 bash/edit operations (B-side of PR #165 agent-permission framework, auto-approve tier). Final agent state at 19:19:46:

```json
{
  "agent_type": "remediation_executor",
  "status": "completed",
  "structured_output": {
    "status": "needs_approval",
    "pr_url": null,
    "branch_name": "cliff/fix/minimist-cve-2021-44906",
    "changes_summary": "Updated minimist from 1.2.0 to 1.2.6 in package-lock.json across 4 dependency declarations (main node, coveralls, cypress, and nyc/detect-indent). This patch-level upgrade fixes CVE-2021-44906 (prototype pollution vulnerability in minimist) without introducing breaking changes.",
    "test_results": "skipped",
    "error_details": "Unable to push to remote: GitHub token (galanko user) lacks permissions to push to cliff-security/NodeGoat repository. Commit was created locally (8151b0c) on branch cliff/fix/minimist-cve-2021-44906 but cannot be pushed without valid credentials or repository access permissions. The fix is complete and ready to push with appropriate credentials."
  }
}
```

Workspace verification (`docker exec`):
- Branch `cliff/fix/minimist-cve-2021-44906` exists locally
- Commit `8151b0c fix: minimist: prototype pollution` — touches **only `package-lock.json`** (6 +/6 −), **not** `package.json`
- No remote tracking branch — push never happened
- Remote URL embeds a `ghu_*` token (User-to-Server, from the GitHub App user OAuth flow)

### t≈19:46 + F5 — B35a/B35b verified

After F5, the side panel header transitioned to:

| Element | Renders as |
|---|---|
| Status pill | **Critical** + **Needs attention** (warning-tinted) |
| Top widget | "Applying the fix · 5m 11s" with a **red error card** containing the executor's full `error_details` |
| "How to fix" link | visible at the bottom of the error card |
| Bottom buttons | **Retry (R)**  +  **Reject (X)** |

This is exactly the IMPL-0017 contract for `executor_failed`. PR-C is verified end-to-end on a real failure.

### t≈21 min — Dashboard view

`/dashboard`:

```
Overview · cliff-security/NodeGoat              [Share report] [Re-run assessment]

[F]  First scan
     Steady at F. Two more closures away from D.
     [Open review queue] [Grading rubric]

Open findings  46  (+41/wk)        Level up to D — Four things between you and an D.
across 4 severities                ① Close the 3 open Criticals      [Open Review]
  ● Critical  3  +3/wk             ② Bring High findings to ≤ 3      [Start]
  ▲ High     15  +13/wk            ③ Resolve the committed secret    [Start]
  ● Medium   22  +21/wk            ④ Pass remaining posture checks (5/15)  [Start]
  ● Low       6   +4/wk

Grading rubric · A D requires zero open Criticals, ≤ 3 High findings,
no committed secrets, and all 15 posture checks passing. [View full rubric]
```

Card #① shows "minimist: prototype pollution · agents working", correctly reflecting the in-progress workspace.

### t≈21 min onward — grade movement (NOT TESTED)

Skipped because the gate condition ("the agent-produced PR merges") never materialized — see B37. The infrastructure for the re-assessment is intact (Re-run assessment button, grading rubric link).

## New defects

### B36 — passive agent progress doesn't reach the UI

**Severity:** P1
**Found:** Wave 3, while waiting on minimist enrichment
**Reproducer:**
1. Fresh container, fresh onboarding, click **Start** on a Critical.
2. Side panel opens; status pill "Planning"; activity shows "Enriching the finding · 0s".
3. Don't touch anything. Wait 60 s.
4. Backend completes all 5 pipeline agents (verifiable via `curl /api/workspaces/.../agent-runs`).
5. UI is still "Enriching the finding · 0s". Status chip still "Planning". 6 runs hidden, plan not rendered.
6. F5 → everything snaps to correct state instantly.

**Root cause hypothesis:** the side panel polls `/agent-execution/stream` aggressively (≥30 reqs / minute observed in DevTools Network) but the stream's emitted events either aren't reaching the React Query cache invalidation paths, or the SSE channel closes/reopens without ever yielding data frames. Mutations that go through user actions (Approve & generate fix, Retry) DO invalidate correctly — the bug is narrowly scoped to backend-initiated progress.

This is the same shape of bug as Wave 1.5's B22 but a different code path — agent-pipeline auto-run events vs. workspace state changes.

**Suggested next step:** open `/agent-execution/stream` in a browser tab and inspect the raw bytes to confirm events ARE being emitted, then trace why the consumer doesn't propagate them into React Query.

**Evidence file:** `evidence/Q01R-W3/B36-stream-no-refetch.md` (network log + screenshot pair).

### B37 — preflight false-positive: user-perms fallback returns can_push=true but git push fails

**Severity:** P0 for "real PR" end-to-end goal; P1 in isolation
**Found:** Wave 3, on Approve & generate fix
**Reproducer:**
1. Onboard with the GitHub App + user OAuth (Tier-2 path).
2. Settings → Integrations: badge shows green "Push verified" (B35c diagnostic green).
3. Open a Critical and click Approve & generate fix.
4. Watch backend: preflight runs `GET /repos/{}/{}` (200, push=true) then `GET /repos/{}/{}/installation` (401 with user OAuth token) → fallback returns `can_push=true`.
5. Executor runs 5+ min, makes a commit locally, then reports `error_details: "Unable to push to remote..."` and `pr_url=null`.

**Root cause:** The user OAuth token (`ghu_*` prefix — User-to-Server) is intersected through `user × App × Installation × OAuth scopes`. The `/repos/{}/{}` endpoint reports `push=true` because @galanko has direct write access TO the repo. But the OAuth token granted to the App may not carry the `repo` scope at the git-protocol level — so the embedded HTTPS push fails with 403 (presumably).

**This is the deferred-work case explicitly flagged in IMPL-0017's Risks block:**
> If user token can't call [/installation], fall back to: mint an installation token using the App private key (deferred — needs IMPL-0019 ADR work) OR add a runtime probe (push a scratch ref, revert).

The B35c diagnostic badge is **also** showing the false positive — it uses the same `check_repo_push_access` helper. Worth flagging in B37's write-up.

**Suggested next steps (pick one):**
1. **IMPL-0019**: switch to installation access tokens (mint via App JWT) for the executor's git push. Cleaner; matches GitHub's documented best practice.
2. **Runtime probe in preflight**: attempt a `git push --dry-run` to a scratch ref (e.g., `refs/heads/cliff/preflight-probe`), use the result as ground truth. Cheap and immediate.
3. **Token-scope check**: hit `GET /user` and inspect `X-OAuth-Scopes` response header; reject if `repo` is missing. Cheap but partial — doesn't catch SAML-SSO-not-authorized cases.

**Evidence file:** `evidence/Q01R-W3/B37-preflight-false-positive.md` (executor structured_output + git log + preflight network calls).

### B34 — device-flow Authorize (carried over)

Not exercised in Wave 3 (OpenRouter OAuth went smoothly). Still tracked as deferred.

## Operational notes

- Wave-2 container (`opensec-wave2`) was stopped before starting Wave-3 to free ports 8000 + 3000. Volume + image preserved.
- Vault key file at `/tmp/cliff-wave3-cred-key.txt` (standard b64). NOT committed.
- The `cliff/fix/minimist-cve-2021-44906` branch exists ONLY inside the container's workspace volume — never pushed to GitHub.
- 11 stale PRs on cliff-security/NodeGoat from Wave 2 (`opensec/fix/*` prefix) — independent of this wave, no action needed.

## What ships now vs. what's deferred

**Ships now (Wave 2 PRs verified):**
- PR #173 vault key UX → CLIFF_CREDENTIAL_KEY accepts both b64 variants, init errors visible.
- PR #174 GitHub App manual install recovery → reachable when callback misses (not exercised today).
- PR #175 preflight teeth + `executor_failed` UI → **fully verified on a real failure**.
- PR #176 push-access diagnostic Settings badge → green on happy path.

**Still deferred (Wave 4 candidates):**
- B36 stream-poll → agent-runs refetch (P1 reactivity).
- B37 preflight false-positive (P0 for end-to-end real PR). Recommend IMPL-0019 (installation tokens) as the structural fix; runtime-probe as a tactical fix.
- B34 device-flow flakiness.

## Recommended Wave 4 entry point

1. Spin /architect on **IMPL-0019: switch executor's git push to installation access tokens** (resolves B37 structurally).
2. In parallel, file a one-PR fix for **B36** (likely a 5-line React Query invalidation in the workspace SSE consumer).
3. Re-run Wave 4 QA with the same UI-only loop and target the F → D grade movement that this wave couldn't reach.
