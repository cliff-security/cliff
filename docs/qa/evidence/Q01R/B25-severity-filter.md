# Q01R-B25 — `/issues?severity=critical` URL filter ignored on load

**Severity**: P2
**Surface**: UI

## What I observed
Clicking "Start" on the dashboard's "Close the 3 open Criticals" card navigates to `/issues?section=todo&severity=critical`. But:
- The Severity filter dropdown still reads "All"
- "Showing all 45" appears in the top-right
- All severities are rendered (Medium, High, Low rows visible)

Manually clicking the Severity dropdown and selecting "Crit" applies the filter correctly and shows "Filtered · 3 of 45".

## Impact
URL filter params don't initialize the dropdown state. Deep links and dashboard navigation land users on an unfiltered view despite the URL claiming a filter.
