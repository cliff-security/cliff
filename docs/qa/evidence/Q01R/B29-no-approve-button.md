# Q01R-B29 — No UI affordance to approve the plan and trigger the executor

**Severity**: P0
**Surface**: UI

## What I observed
After agents completed for the minimist finding, the workspace sidebar JSON showed:
```
plan: {
  plan_steps: [6 concrete steps],
  approved: false,        ← needs approval
  ...
}
active_plan_version: null
```

The side panel rendered the 5 completed agent runs and the plan content (in the "Drafting the plan" card: "Upgrade minimist from 1.2.0 to 1.2.6 to remediate CVE-2021-44906…") but offered **no Approve button anywhere**:
- No button at the top of the panel
- No button in the plan card
- No button at the bottom (just "Thinking… / Cancel run")
- No button on the Issues row

The API supports it: `POST /api/workspaces/{wsid}/plan/approve` returns 200 OK and flips `plan.approved=true`. The UI just doesn't surface it.

## Recreate
1. Click Start on any non-posture finding
2. Wait for the planner agent to complete
3. Try to find a way to approve the plan or run the executor from the UI

## Impact
**This is the hardest blocker found.** UI-only users (which the campaign now mandates) cannot drive a remediation past the plan stage. The remediation_executor never runs without a manual `curl` call. PR creation, file changes, downstream validation — all unreachable.

## Suggested fix
Add an "Approve plan" button next to the plan card once the planner completes. After approve, surface a "Run executor" button (or auto-run with a confirmation modal explaining what will happen — write code, push branch, open PR).

## Workaround used in this session
Called `POST /api/workspaces/<wsid>/plan/approve` and `POST /api/workspaces/<wsid>/pipeline/run-all` via curl to bypass the missing UI.
