# IMPL-0012: Q01R — UI reactivity + plan approval flow

**Scope:** Wave 1.5 (Q01R) bug fixes — UI/UX cluster
**Bugs:** B22, B25, B26, B27, B28, B29
**Owner:** App Builder (V2)
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

Six of the nine Q01R defects share root causes in two narrow areas:

1. **State reactivity** — the same "poll only while there's work; show 'Thinking…' as default" pattern is used in three places (OpenRouter OAuth, agent runs, panel footer). It breaks in the same way each time: when the parent tab regains focus or the last agent completes, the UI doesn't re-check, so it stays on the loading state forever. B22, B28, and B29 are all instances of this.
2. **Workflow plumbing** — URL parameters aren't hydrated into component state (B25), dashboard rec-card buttons just navigate instead of starting a workspace (B27), and the "Review is clear" success card fires in the wrong condition (B26).

This plan fixes both clusters in one wave with a single React polling/state-sync change, one small Issues-page refactor, and one tiny copy/visibility tweak.

**Why one plan, not six:** the B28/B29 link is structural — fixing the polling makes the existing footer Approve button render, which is most of B29 in one shot. B22 shares the same polling-loop topology. Treating them together makes the diff smaller and the test surface smaller.

## Root causes (grounded in code)

| Bug | File:line | Current behavior | Required change |
|---|---|---|---|
| B22 | `frontend/src/api/aiProvider.ts:176–223` (`useOpenRouterPolling`) | Polls `/api/integrations/ai/openrouter/status?session_id=…` every 1s while `status === 'waiting'`. No window-focus refetch, no fallback to `/api/integrations/ai/status` after the in-memory session is evicted | (a) add `window.focus` listener that refetches while session is open, and (b) treat `/api/integrations/ai/status: { connected: true, provider: 'openrouter' }` as a terminal "completed" signal even if the per-session record is gone |
| B28 | `frontend/src/api/hooks.ts` `useAgentRuns` `refetchInterval: hasActive ? 3000 : false` | Polling stops the moment all agents complete; activity log only refreshes on panel re-mount | Always poll at 5s when a workspace is open; bump to 2s while `hasActive` is true. Keep it dead-simple — no SSE for now |
| B29 | `frontend/src/components/issues/IssueSidePanel.tsx` `DefaultFooter` stage=`plan_ready` | Button exists ("Approve & generate fix") but is only rendered after `stage` transitions to `plan_ready`, which depends on B28's stale polling. Onclick calls `executeAgent.mutate({agentType:'remediation_executor'})` directly — skips `/plan/approve` so sidebar.plan.approved stays `false` | (a) B28 fix unlocks the stage transition, (b) wrap the onclick in an approve-then-execute sequence so the audit trail (sidebar.plan.approved=true) is correct |
| B25 | `frontend/src/pages/IssuesPage.tsx:54` `useState('all')` | Local state initialized without reading `useSearchParams()`; URL `?severity=critical` is ignored | Initialize `severityFilter` (and `typeFilter`) from `searchParams.get(...)` on mount; write back on change with `setSearchParams` |
| B26 | `frontend/src/pages/IssuesPage.tsx:313` `showEmptyReviewCard = sections.review.length === 0 && (other sections > 0)` | Big green check + "Review is clear" appears whenever the (separate) Review queue is empty — even with 45 items in Todo | Hide the empty-review card whenever `todo.length > 0`. Rename heading to "Manual review queue is clear" to disambiguate from the rest of the page |
| B27 | `frontend/src/components/dashboard/GateRow.tsx:46–60` `onClickAction` | Pure `onNavigate?.(gate.action_href)`; the gate payload doesn't carry a finding id | Backend `_level_up.py` adds `first_finding_id` to each gate's payload; href becomes `/issues?...&open=<finding_id>`. Frontend continues to just navigate — the existing `?open=<id>` convention already auto-opens the side panel |

## Files touched

Frontend (V2):
- `frontend/src/api/aiProvider.ts` — `useOpenRouterPolling`: add focus listener + `/api/integrations/ai/status` fallback
- `frontend/src/api/hooks.ts` — `useAgentRuns`: always poll at 5s (2s when active)
- `frontend/src/components/issues/IssueSidePanel.tsx` — `DefaultFooter` plan_ready onclick: approve → execute
- `frontend/src/pages/IssuesPage.tsx` — `severityFilter` / `typeFilter` hydrate from URL; `showEmptyReviewCard` adds `&& todo.length === 0`; heading copy

Backend (V2):
- `backend/opensec/api/routes/_level_up.py:_posture_gate()` and the dependency / secret / high-finding gate builders — add `first_finding_id` (and `first_action_href`) so frontend can deep-link to side panel
- `backend/opensec/api/routes/ai_integrations.py` — `openrouter_status()` keeps the session alive long enough that late polls still return `completed` (or returns synthetic `completed` if `/api/integrations/ai/status` confirms openrouter is connected)

No ADR needed — this is wiring within ADR-0021 (agent execution model) and ADR-0036 (AI provider integration) boundaries.

## Test plan (TDD-first)

Unit (frontend, Vitest):
- `useOpenRouterPolling.test.tsx` — simulate window focus while session is `waiting`, expect refetch fired
- `useOpenRouterPolling.test.tsx` — when `/openrouter/status` 404s but `/ai/status: {connected: true, provider: 'openrouter'}`, hook resolves as "completed"
- `useAgentRuns.test.tsx` — polling interval is 5000 when no active runs, 2000 when active
- `IssuesPage.test.tsx` — mount with `?severity=critical&type=dependency` and assert filter dropdowns reflect URL
- `IssueSidePanel.test.tsx` — at stage `plan_ready`, clicking the footer button fires approve then execute (verify mock call order)

Unit (backend, pytest):
- `test_level_up.py` — each gate's payload includes `first_finding_id` when at least one finding matches; `action_href` ends with `&open=<id>`
- `test_routes_ai_integrations.py` — `GET /openrouter/status?session_id=<stale>` after credential was saved returns a `completed` payload (or a synthetic one cross-referencing `/ai/status`)

E2E (manual, captured by Wave-2 re-run of Q01):
- Onboarding step 2 — authorize OpenRouter, switch back to Cliff tab without manual reload, expect "Connected to OpenRouter" within 2s of returning
- Open a Critical finding, wait for plan stage to complete, observe activity log refreshes within 5s and footer "Approve & generate fix" button appears without panel re-open
- Click "Approve & generate fix", inspect `GET /api/workspaces/{id}/sidebar.plan.approved` is `true` AND `remediation_executor` agent has started

## Risks

- **5s background polling on multiple open workspaces could be noisy.** Mitigation: only poll while a side panel is open (already the case for `useAgentRuns`); polling is bound to the panel mount.
- **Wrap onclick approve→execute could double-trigger executor on retry.** Mitigation: the approve route is idempotent (200 OK whether `approved` is already true). The execute route already has anti-double-fire (`hasActive` check).
- **OpenRouter fallback to `/ai/status` may misfire if the user re-onboards a different provider.** Mitigation: gate on `provider === 'openrouter'` in the fallback.

## Rollout

Single PR, one commit per fix, conventional commit prefix `fix(q01r-ui):`. Target branch: `main`. Wave 2 will re-run Q01 against the merged build.
