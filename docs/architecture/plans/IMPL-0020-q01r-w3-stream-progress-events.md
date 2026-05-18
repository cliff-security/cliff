# IMPL-0020: Q01R Wave 3 — agent-execution stream emits progress events (fix for B36)

**Scope:** Wave 3 (Q01R-W3) — make the side panel reflect backend agent-pipeline progress without manual refresh.
**Bug:** B36 (P1)
**Owner:** App Builder (V2) — `backend/cliff/api/routes/agent_execution.py`, `backend/cliff/agents/executor.py` (publish side), `frontend/src/components/issues/IssueSidePanel.tsx` (consume side).
**Status:** Draft — needs CEO approval
**Date:** 2026-05-18

## Summary

The `GET /api/workspaces/{wid}/agent-execution/stream` endpoint currently emits only two event types: `permission_request` (for ask-tier tool approval) and `done` (for executor exit). It does NOT emit agent-pipeline progress — no `agent_run_started`, `agent_run_completed`, `context_updated`. The frontend's SSE consumer at `IssueSidePanel.tsx:196` listens only for `permission_request` and the polled `useAgentRuns` is supposed to handle the rest. In practice (verified Wave 3 QA), passive backend progress is invisible to the UI until F5.

This isn't a regression — it's a design gap. The stream was scoped to permission prompts when added in PR #165 (agent-permission framework). The pipeline auto-run path that powers the enricher→owner→exposure→evidence→planner chain never wired itself into the workspace's event queue.

**Simplest correct fix:** when `executor` (or the pipeline orchestrator) transitions an agent run, push an event into the workspace queue. The existing SSE endpoint forwards anything in the queue, so the only generator-side change is to publish more event kinds. Extend the frontend SSE consumer to invalidate `agent-runs` on `agent_run_completed` events (and optionally `agent_run_started` for finer-grain refreshes).

## Why not just rely on poll?

The polled fallback exists (`useAgentRuns`'s `refetchInterval`) at 5s idle / 2s active. In Wave 3 QA the idle poll didn't fire reliably under the MCP-driven browser interaction; a human with the tab in foreground may or may not see the same issue. Regardless, the SSE channel is the architecturally correct surface for "backend state changed, UI please refresh" — and we already have it open. Closing the gap on its emit side is cheaper than debugging React Query's poll-cadence behavior across browsers + window-focus states.

## Root cause (grounded in code)

**Backend — emit side:**
- `backend/cliff/api/routes/agent_execution.py:520-587` `stream_agent_execution` — generator yields whatever is in `executor.get_permission_queue(workspace_id)`. Today the queue only carries `permission_request` and `done`.
- `backend/cliff/agents/executor.py` (and the pipeline orchestrator that calls it) — never publish "I started agent X" or "I finished agent X" events.

**Frontend — consume side:**
- `frontend/src/components/issues/IssueSidePanel.tsx:175-205` — SSE consumer with one listener: `permission_request`. Per the comment: "this just lets the row light up instantly when the panel is already open. On any SSE error we silently fall back to polling — no user-visible failure, no reconnection storm."

The poll fallback isn't reliable in the actual QA scenarios we run; the SSE channel is open anyway. Use it.

## Files touched

Backend (V2):
- `backend/cliff/agents/executor.py` (or wherever the pipeline orchestrator publishes events) — when an agent run transitions to `completed` (success or failure), push:
  ```python
  {"type": "agent_run_completed", "agent_type": "<name>", "run_id": "<uuid>", "status": "completed|failed"}
  ```
  Mirror for `agent_run_started`. The exact insertion point is whatever publishes to the queue today for permission events — grep for `permission_queue.put` or similar.
- `backend/cliff/api/routes/agent_execution.py:564-577` — extend the dispatch logic so events with `type in {"agent_run_started", "agent_run_completed"}` get emitted as their own named SSE event (`yield {"event": "agent_run_completed", "data": json.dumps({...})}`). Today the dispatch defaults all non-done events to `permission_request` — this needs to switch on `event_type`.

Frontend (V2):
- `frontend/src/components/issues/IssueSidePanel.tsx:191-204` — add listeners for `agent_run_completed` and `agent_run_started` that both call the same `nudge` (invalidate `['agent-runs', workspaceId]`). Optionally also invalidate `['sidebar', workspaceId]` so the stage chip refreshes immediately.

Tests:
- `backend/tests/test_routes_agent_execution.py` — extend stream tests to verify that pushing `{"type": "agent_run_completed", ...}` to the queue emits an `event: agent_run_completed` SSE frame with the expected data shape.
- `frontend/src/components/issues/__tests__/IssueSidePanel.test.tsx` — assert that a mocked `agent_run_completed` event triggers `queryClient.invalidateQueries({queryKey: ['agent-runs', workspaceId]})`.

## Test plan (TDD-first)

Backend (pytest):
```python
async def test_stream_emits_agent_run_completed(workspace_with_queue):
    workspace_with_queue.put({"type": "agent_run_completed", "run_id": "abc", "status": "completed"})
    async with sse_client(...) as stream:
        evt = await stream.next_event(timeout=2.0)
        assert evt.event == "agent_run_completed"
        assert json.loads(evt.data)["run_id"] == "abc"
```

Frontend (vitest):
```typescript
it("invalidates agent-runs when SSE emits agent_run_completed", async () => {
  const spy = vi.spyOn(queryClient, "invalidateQueries")
  render(<IssueSidePanel finding={...} workspaceId="w1" />)
  mockEventSource.emit("agent_run_completed", { run_id: "r1" })
  await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["agent-runs", "w1"] }))
})
```

Then implement.

E2E (Wave 4 QA, manual): open a side panel, click Start, do not touch anything. Within ~1s of each backend pipeline step completing, the activity feed should add the corresponding run. No F5 should be required.

## Risks

- **Event-storm:** the pipeline emits 5 agents in ~45s. That's 10 events (5 started + 5 completed). React Query coalesces `invalidateQueries` within a render cycle, so 10 invalidations in 45s won't thrash. No-op.
- **Event ordering with poll:** if the SSE event arrives before the database row is committed (race), the immediate refetch sees stale data and another refetch happens 5s later via the idle poll. Acceptable — at most one extra round-trip.
- **Bleeding into other surfaces:** invalidating `['agent-runs', wid]` and `['sidebar', wid]` is scoped per workspace. No cross-workspace blast.
- **Stream that today early-yields `done` when queue is empty (line 540) will keep doing so — fine.** New events only fire when there's an active run.

## ADR

No new ADR required. ADR-0008 (sub-agent architecture) and ADR-0014 (workspace runtime) already cover this surface. The SSE channel was added in PR #165 with permission-prompt scope; this extends it without changing the architecture.

## Rollout

Single PR, 3 commits:
1. `feat(q01r-w3-stream): emit agent_run_started/completed events on workspace queue (B36)`
2. `feat(q01r-w3-stream): frontend listens for run-progress events and invalidates agent-runs`
3. `test(q01r-w3): regression tests for stream progress events`

Target branch: `main`.

## Out of scope (Wave 4 deferrals)

- Adding `context_updated` events. Useful but adds complexity for marginal gain — the agent-runs invalidation transitively triggers a sidebar refresh via the existing chain.
- Reconciling poll-cadence behavior under MCP-driven testing. The SSE fix removes our dependency on the poll's reliability; if poll behavior still surfaces other issues in Wave 4 QA, address then.
