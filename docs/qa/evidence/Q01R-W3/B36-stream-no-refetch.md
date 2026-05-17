# B36 — `/agent-execution/stream` poll fires but never triggers `/agent-runs` refetch

**Severity:** P1
**Wave:** Q01R-W3
**Found:** 2026-05-17, while waiting on the minimist@1.2.0 enrichment pipeline
**Build:** `cliff:wave3` from `main = 8139bad`

## Reproduce

1. Fresh container with onboarding complete (GitHub App + AI provider).
2. Click **Start** on any Critical finding (used `minimist: prototype pollution`, id `bf65697b-…`).
3. The side panel opens with status pill "Planning" and activity "Enriching the finding · 0s".
4. **Do not refresh, do not click anywhere.** Wait 60 s.
5. Observe: backend has finished all 5 pipeline agents, but the side panel still shows "Enriching the finding · 0s" with a single run.
6. Press F5. The UI instantly snaps to the correct state — "Plan ready" pill, 6 runs visible, 6-step plan rendered, "Needs you" swim lane populated.

## Network panel snapshot (during the 60-s wait)

```
1   GET /api/dashboard                                                  200
2   GET /api/findings?scope=current                                      200
3   POST /api/workspaces                                                 201
4   POST /api/workspaces/<wid>/pipeline/run-all                          202
5   GET /api/workspaces/<wid>/agent-runs                                 200   ← ONLY fetch
6   GET /api/integrations/ai/status                                      200
7   GET /api/workspaces/<wid>/agent-execution/stream                     200
8   GET /api/workspaces/<wid>/agent-execution/stream                     200
…
40  GET /api/workspaces/<wid>/agent-execution/stream                     200
```

40 stream polls. ONE `/agent-runs` fetch (#5, at t=0). No further `/agent-runs`, `/sidebar/state`, or workspace fetches across the entire pipeline run.

## Backend observation

Backend logs during the same 60 s:

```
19:10:41  cliff.workspace.context_builder: Updated context … finding_enricher -> v1
19:10:49  cliff.workspace.context_builder: Updated context … owner_resolver -> v2
19:10:57  cliff.workspace.context_builder: Updated context … exposure_analyzer -> v3
19:11:05  cliff.workspace.context_builder: Updated context … evidence_collector -> v4
19:11:15  cliff.workspace.context_builder: Updated context … remediation_planner -> v5
```

The pipeline finished server-side in 45 s. The UI sat on stale state for 90+ s until F5.

## Verified by curl during the dead window

```bash
$ curl -s http://localhost:8000/api/workspaces/<wid>/agent-runs | jq '.[].agent_type, .[].status'
"remediation_planner"   "completed"
"evidence_collector"    "completed"
"exposure_analyzer"     "completed"
"owner_resolver"        "completed"
"finding_enricher"      "completed"
```

So the backend's `/agent-runs` was correct. The frontend just wasn't asking.

## Mutations DO invalidate correctly

After F5, I clicked **Approve & generate fix**. The mutation immediately updated the side panel (status pill flipped to "Generating fix", new top run "Applying the fix" appeared). So React Query's invalidation works for mutation callbacks — the bug is narrowly scoped to **backend-initiated progress**: the SSE/poll channel that's supposed to push pipeline-state changes either yields no usable events or its consumer doesn't propagate them.

A similar dead window then opened during the executor run (5m 11s "Applying the fix · 0s") until F5 again.

## Hypothesis

Two possibilities, mutually exclusive — needs a one-tab-open inspect of the `/agent-execution/stream` raw response to confirm:

**(a) Stream is alive but consumer is broken.** SSE body is emitting `event: agent_completed` frames but the React Query consumer either:
- doesn't subscribe to them, or
- subscribes but doesn't call `queryClient.invalidateQueries(['agent-runs', wid])`.

**(b) Stream is broken.** Server keeps closing the response after a handful of seconds (40 polls / 60 s ≈ 1.5 s/poll, consistent with a Connection: close + reconnect storm rather than a long-lived SSE), and never actually emits payload before closing. In this case the stream is effectively just a 30-times-per-minute heartbeat.

The fix differs by hypothesis. (a) is a single-file React Query change. (b) is a server-side `EventSourceResponse` plumbing fix in `backend/cliff/api/routes/agent_execution.py`.

## Suggested next step

Open `http://localhost:8000/api/workspaces/<wid>/agent-execution/stream` in a separate browser tab while a workspace is mid-pipeline. If you see live `data: …` lines streaming, it's (a). If the response closes after milliseconds with no body, it's (b).

## Relationship to B22 (Wave 1.5)

B22 was specifically about the **Issues counter** ("In progress 0 → 1" reactivity). That fix held — when I clicked Start, the counter did flip from 0 to 1. B36 is the same shape of bug — passive backend progress not propagating — but on a different surface (side-panel activity feed instead of issues-page counter).
