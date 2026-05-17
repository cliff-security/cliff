# Q01R-B27 — Dashboard "Start" card buttons navigate to filtered Issues list rather than driving the work

**Severity**: P2
**Surface**: UI

## What I observed
Dashboard "Level up to D" listed four actions, each with a "Start" button:
- "Close the 3 open Criticals" → `Start →`
- "Bring High findings to ≤ 3" → `Start →`
- "Resolve the committed secret" → `Start →`

Each button just navigates to `/issues?...` with a (broken — see B25) filter param. No agent is started, no side panel auto-opens, no plan is generated.

User has to then click "Start" again on an individual row to actually kick off the agent pipeline.

## Suggested fix
Dashboard "Start" should at minimum auto-open the first matching finding's side panel. Better: optionally batch-start all findings in the group (e.g., "Start all 3 Criticals → plan in parallel, ask before executing").
