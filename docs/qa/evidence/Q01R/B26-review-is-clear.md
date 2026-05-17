# Q01R-B26 — "Review is clear" + green check shown when 45 issues are queued

**Severity**: P3 (UX clarity)
**Surface**: UI

## What I observed
Issues page header shows a giant green check + "Review is clear." even when the Todo queue has 45 items.

Sub-text: "All open issues are either in progress or in the Todo queue. The next thing that needs you will land here."

## Impact
User opens Issues, sees the "all clear" check, may close the tab thinking they're done. The actual queue is below. Confusing visual hierarchy: success treatment for a state that requires action.

## Suggested fix
Either:
- Reserve the green check + "Review is clear" for when the Todo queue is empty
- Or rename "Review" so it doesn't read like "Issues" — "Manual review queue" vs "Todo queue" is the distinction the design intends but doesn't convey
