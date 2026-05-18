# EXEC — Q01R Wave 3 execution sequencing

**Date:** 2026-05-18
**Status:** Draft — needs CEO approval
**Goal:** Land the two Q01R-W3 fixes (B36, B37) so Wave 4 QA can finally drive a Critical to a real PR on cliff-security/NodeGoat via UI alone.

## Bugs → plans → owners

| Bug | Sev | Plan | Owner |
|---|---|---|---|
| B37 — preflight false-positive (push not actually possible) | P0 (for end-to-end goal) | IMPL-0019 | App Builder (V2) |
| B36 — stream poll doesn't trigger agent-runs refetch | P1 | IMPL-0020 | App Builder (V2) |

Both bugs sit within App Builder (V2) territory. No Agent Orchestrator (V1) work.

## Sequencing

Both PRs are file-independent. They can ship in parallel.

Per the Wave 1.5 / Wave 2 pattern:

1. **PR-Q01R-W3-A (IMPL-0019):** push-access runtime probe
    - Closes B37
    - 1-2 commits; ~50 lines backend + 3 tests
    - Conventional commit prefix `feat(q01r-w3-probe):`
2. **PR-Q01R-W3-B (IMPL-0020):** SSE stream progress events
    - Closes B36
    - 2-3 commits; backend stream extension + frontend listener + tests
    - Conventional commit prefix `feat(q01r-w3-stream):`

Both target `main`.

## Exit criteria (Wave 4 must verify)

Re-run the UI-only QA flow that found B36 and B37. Ship when:

- Settings → Integrations: Push verified badge ONLY shows green when the configured token can actually push to the configured repo at the git-protocol layer (B37/IMPL-0019).
- Side panel: clicking Start on a Critical surfaces each pipeline-step transition (Enriching → Resolving owner → Analyzing exposure → Collecting evidence → Drafting the plan → Plan ready) within ~1s, with NO F5 required (B36/IMPL-0020).
- End-to-end: a Critical with correct setup drives to a real PR on cliff-security/NodeGoat — the original promise of B30, finally achievable now that the preflight returns ground truth.
- The Wave 4 re-run assessment moves the grade F → D after the agent-produced PR merges (the gate Wave 3 couldn't reach).

## What's explicitly out of scope this wave

- **IMPL-0021** (installation access tokens via App JWT) — deferred again. The runtime probe in IMPL-0019 unblocks the end-to-end story without it; the structural cleanup can wait until a follow-up wave or until a use case for non-user-bound execution (scheduled re-assessments) emerges.
- Reconciling React Query's `refetchInterval` cadence under MCP-driven testing. IMPL-0020's SSE fix removes our dependency on poll cadence; if poll behavior surfaces other issues in Wave 4, file them.
- **B34** (device-flow Authorize flakiness) — still deferred, not exercised in Wave 3.

## Tracking

Tasks land in `docs/BACKLOG.md` under App Builder (V2) as Q29-Q31 (continuing the Q1-Q28 numbering from Waves 1.5 and 2). Each PR closes its corresponding Q-tasks.
