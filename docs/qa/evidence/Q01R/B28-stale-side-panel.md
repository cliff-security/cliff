# Q01R-B28 — Workspace side panel "Plan / Thinking…" widget stays stale after agents complete

**Severity**: P1
**Surface**: UI

## What I observed
After clicking "Start" on a minimist Critical finding:
1. Side panel opened, top widget showed "Reviewing the advisory and the call sites… / We'll surface the result when it's ready."
2. Activity log showed "Enriching the finding (0s)"
3. ~60 seconds later, backend confirmed all 5 plan-stage agents completed (enricher, owner, exposure, evidence, planner)
4. Side panel TOP widget remained on "Reviewing… / Thinking…" indefinitely
5. Only after closing the panel and re-opening it did the activity log update to show all 5 completed runs with confidence scores and outputs

The bottom of the panel still shows "Thinking — We'll notify you when the next step is ready" even when the next step is ready and waiting on user action (see B29).

## Impact
Identical symptom to B22 (OAuth polling) — UI doesn't pick up backend state changes without a manual refresh. User sees a spinning widget for what's actually a completed pipeline.

## Suggested fix
Tighten the polling interval, or use SSE (the API already exposes `/agent-execution/stream`). The "Thinking…" bottom widget needs to clear once the planner completes and reflect the actual next state ("Plan ready — review and approve").
