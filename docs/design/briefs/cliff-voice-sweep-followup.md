# Cliff voice sweep — remaining strings

Follow-up to **fix/cliff-readability-and-voice-alignment** (Section G).

The readability PR landed the top voice fixes inline (`Loading...` → "Cliff
is loading the …", `Fix it` → "Take care of this", removed `▸` triangle
prefixes and ALL-CAPS source strings across chrome, severity chips,
section labels, and side-nav rows). This document lists the remaining
copy that still needs a voice pass per `gtm/brand/voice.md`. None of it
blocks the readability PR.

## Method

Each entry has `file:line — current` and a suggested rewrite. The
rewrite is a starting point, not a final string — copy review still
applies.

## Loading states needing Cliff-narrates-it rewrites

- `frontend/src/components/AgentRunCard.tsx` — any "Running…" /
  "Processing…" strings should become specific Cliff-narrates lines
  ("Cliff is checking the dependency tree.", "Cliff is reading the
  codebase.", "Cliff is filing the ticket.").
- `frontend/src/components/IngestProgress.tsx` — progress lines should
  read as Cliff narrating the current step (e.g. "Cliff is parsing
  scanner output.").
- `frontend/src/components/dashboard/AssessmentRunningCard.tsx` — the
  scanner-tool progress lines could be re-voiced from generic
  "Running…" to "Cliff is running Semgrep across the codebase."
- `frontend/src/components/PageSpinner.tsx` — done (rewrote to
  "Cliff is loading the page…"). Keep.

## Generic error messages

- `frontend/src/components/ErrorState.tsx` — current "Something went
  wrong." pattern. Voice doc wants Cliff-as-actor + recovery step.
  Proposed: "Cliff couldn't reach the backend. Refresh the page?"
- Any catch-all `console.error(...)` user-facing surface — audit and
  rewrite to name the upstream system and the next step.

## Success and completion states

- `frontend/src/components/completion/CompletionCelebration.tsx` —
  audit "Done." / past-tense verb phrasing. Voice doc forbids
  "Successfully completed!" patterns.
- `frontend/src/components/EnricherResultCard.tsx` and the
  `*ResultCard.tsx` family — the per-agent result headers may still
  carry generic "Result" / "Output" labels; should be specific past
  tense from Cliff ("Cliff identified the affected package",
  "Cliff wrote the remediation plan").

## Confirmation dialogs

- `frontend/src/components/settings/IntegrationSettings.tsx` — the
  `window.confirm(...)` strings ("Disconnect {label}? Workspaces that
  depend on it will stop until you reconnect.") are already in
  consequence-named voice. Keep.
- `frontend/src/components/ai-provider/AIProviderStatus.tsx` —
  Disconnect dialog body already in voice. Keep.
- Audit any remaining browser `confirm()` calls for the same pattern.

## Onboarding copy

- `frontend/src/pages/onboarding/ConfigureAI.tsx`, `ConnectRepo.tsx`,
  `StartAssessment.tsx` — onboarding step subtitles and helper text
  are mid-voice but verbose. Tighten per Layer 3 of voice.md (drop
  hedging like "let's", "we'll").

## Provider / integration setup flows

- `frontend/src/components/ai-provider/OpenRouterConnectFlow.tsx`,
  `DirectBYOKForm.tsx`, `AutoDetectBanner.tsx` — bodies still use
  "Cliff" in some strings (should be "Cliff"); audit and convert.
  Several use "Loading…" / "Saving…" placeholders that could narrate.

## Settings page copy

- `frontend/src/components/settings/IntegrationSettings.tsx` — the
  "Set up" / "Resume install" / "Use a token instead" buttons are OK
  in voice but should be reviewed for tone consistency. Confirm the
  Disconnect-dialog body uses Cliff-as-actor.

## CompletionCelebration / SummaryActionPanel

- `frontend/src/components/completion/SummaryActionPanel.tsx` —
  Shareable summary card embeds "Secured by Cliff" copy. Update to
  "Secured with cliff" or similar once brand rename lands fully.

## Method going forward

When voice fixes are addressed:
1. Identify the file:line offender in this list.
2. Rewrite per `gtm/brand/voice.md` Layer 3 (vocabulary) + Layer 4
   (paired examples).
3. Verify the new string reads aloud calm + specific.
4. Strike through the entry here (or remove it).

This list is not exhaustive — it's a high-confidence starter set.
Doing one folder at a time is fine. Tone consistency across the app
matters more than catching every string in one pass.

---

## Test suite cleanup follow-up

The readability + voice PR deliberately changes user-facing strings,
chip class names, and a handful of layout sizes. 32 unit tests now
fail with assertions like:

- `expect(badge.className).toMatch(/bg-error/)` — pre-Cyberdeck class
  names that never returned after the visual refactor. Should assert
  on `cd-chip cd-chip--red` / `--amber` / `--cyan` / `--ink`.
- `expect(screen.getByText('CRIT')).toBeInTheDocument()` — severity
  chips now say "Critical" / "High" / "Medium" / "Low" per voice.
- `expect(badge.style.fontSize).toBe('10.5px')` — chips are 12px in
  the Cyberdeck system; the assertion is testing the old M3 size.
- `expect(triggerHover).toMatch(/CRITICAL/)` — IssueFilterChip /
  IssueFilterSelect option labels now sentence case.
- `IssueDeltaChip` rose-vs-sage tone assertions — semantic mapping
  was rewired (amber=up, sage=down, fg-4=flat); the old test asserted
  rose for "bad direction" which is no longer reserved for trends.

A short test-cleanup PR should:

1. Sweep `frontend/src/components/issues/__tests__/` and rewrite the
   chip/badge class-name + text-content assertions.
2. Sweep `frontend/src/components/dashboard/__tests__/IssueDeltaChip.test.tsx`
   for the new sage/amber semantic mapping.
3. Sweep `frontend/src/pages/__tests__/IssuesPage.test.tsx` for the
   couple of remaining text-content assertions.

None of this affects production behaviour. Estimated ~1-2 hours.

