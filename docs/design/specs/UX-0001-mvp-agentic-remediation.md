# UX-0001: MVP — agentic remediation experience

**PRD:** docs/product/prds/PRD-0001-mvp-minimum-value-product.md
**Status:** Approved
**Date:** 2026-04-09

---

## Design principles for this spec

1. **Calm authority:** The user is dealing with security findings. Every screen should make them feel in control, never overwhelmed.
2. **Progressive disclosure:** Show the essential info first, let the user drill in. Don't dump everything at once.
3. **The chat IS the workspace:** The collaborative chat is the primary work surface — not a sidebar or afterthought.
4. **Show progress, not complexity:** The user should always know where they are in the pipeline and what to do next.

---

## Screen inventory

| Screen | Change type | Stories covered |
|---|---|---|
| Findings page — empty state | New | S1, S2 |
| Findings page — import dialog | New | S1 |
| Findings page — import progress | Modified (wire existing IngestProgress) | S1 |
| Findings page — populated with status | Modified | S2, S7 |
| Settings page — repository section | New | S3 |
| Workspace page — updated action chips | Modified | S4 |
| Workspace page — structured result cards | New components | S5 |
| Workspace page — remediation flow | New interactions | S6 |
| Workspace page — PR created state | New | S6 |
| Workspace sidebar — updated sections | Modified | S5, S6 |
| Error states (all pages) | New component | G10 |

---

## Component breakdown

### New components

| Component | Purpose | Used in |
|---|---|---|
| `ImportDialog` | Modal with file upload + JSON paste tabs | Findings page |
| `ImportButton` | Toolbar button that opens ImportDialog | Findings page toolbar |
| `EnricherResultCard` | Structured card for Finding Enricher output | Workspace chat |
| `ExposureResultCard` | Structured card for Exposure Analyzer output | Workspace chat |
| `PlannerResultCard` | Structured card for Remediation Planner output | Workspace chat |
| `RemediationResultCard` | Structured card for Remediation Executor output (diff + PR link) | Workspace chat |
| `PlanApprovalCard` | Interactive card: approve/modify plan before agent executes | Workspace chat |
| `PRStatusBadge` | Shows PR state (draft/open/merged) with GitHub link | Workspace sidebar, Findings page |
| `ConfidenceBadge` | High/medium/low confidence indicator | All result cards |
| `SuggestedActionHighlight` | Visual emphasis on the recommended next action chip | Workspace action chips |
| `RepoSettingsSection` | GitHub repo URL + PAT + test connection | Settings page |
| `ErrorState` | Error display with icon, title, message, retry button | All pages |

### Existing components to modify

| Component | Change | Reason |
|---|---|---|
| `ActionChips` | Remove "Find owner", add "Remediate". Add highlight state for suggested next action | Pipeline is now Enrich → Exposure → Plan → Remediate |
| `EmptyState` | Add variant with import CTA for Findings page first-run | G2 onboarding |
| `WorkspaceSidebar` | Replace "Owner" section with "Pull request" section. Replace "Ticket" section with "Repository" | MVP persona doesn't use owner resolution or ticketing |
| `FindingRow` | Add PR link icon column. Update status badge colors for new states | G8 status flow |
| `SeverityBadge` | No change needed — already compliant | — |
| `ResultCard` | Keep as fallback for unstructured results. New typed cards render instead when structured data available | G3 |

---

## Interaction flows

### Flow 1: First run — import findings (Stories 1 + 2)

**Entry point:** User opens Cliff for the first time. Findings page is empty.

```
┌─────────────────────────────────────────────────────┐
│ Findings page — empty state                          │
│                                                      │
│    ┌──────────────────────────────────┐              │
│    │  (icon: assignment_late)          │              │
│    │                                   │              │
│    │  No findings yet                  │              │
│    │                                   │              │
│    │  Import findings from your        │              │
│    │  scanner to get started.          │              │
│    │                                   │              │
│    │  [Import findings]  ← primary btn │              │
│    │                                   │              │
│    │  Supports Snyk, Wiz, and other    │              │
│    │  JSON exports                     │              │
│    └──────────────────────────────────┘              │
│                                                      │
│  Also: toolbar always shows [Import findings] button │
└─────────────────────────────────────────────────────┘
```

**Step 1: User clicks "Import findings"**

Import dialog opens as a centered modal overlay.

```
┌─────────────────────────────────────────────────────┐
│ Import findings                              [×]     │
│                                                      │
│ ┌──────────┐ ┌──────────┐                           │
│ │ Upload   │ │ Paste    │  ← tabs                   │
│ └──────────┘ └──────────┘                           │
│                                                      │
│ [Upload tab — active by default]                     │
│                                                      │
│ ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐       │
│ │                                            │       │
│ │  (icon: upload_file)                       │       │
│ │                                            │       │
│ │  Drop a JSON file here, or click           │       │
│ │  to browse                                 │       │
│ │                                            │       │
│ │  Accepts .json up to 10MB                  │       │
│ └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘       │
│                                                      │
│ [Paste tab — shows textarea]                         │
│                                                      │
│ Tested with: Snyk, Wiz, and generic formats          │
│                                                      │
│                         [Cancel]  [Import]            │
└─────────────────────────────────────────────────────┘
```

**Step 2: File selected → Import starts**

Dialog transitions to progress view:

```
┌─────────────────────────────────────────────────────┐
│ Importing findings                           [×]     │
│                                                      │
│ sample-snyk-export.json                              │
│                                                      │
│ ████████████░░░░░░░░░░░░  12 of 28 findings         │
│                                                      │
│ Normalizing finding data...                          │
│                                                      │
│ ✓ 10 imported  · 2 processing  · 0 failed            │
│                                                      │
│                                        [Cancel]      │
└─────────────────────────────────────────────────────┘
```

**Step 3: Import complete**

Dialog shows summary, auto-closes after 3s or on click:

```
┌─────────────────────────────────────────────────────┐
│ Import complete                              [×]     │
│                                                      │
│ (icon: check_circle — tertiary color)                │
│                                                      │
│ 28 findings imported successfully                    │
│                                                      │
│ 6 critical · 8 high · 10 medium · 4 low             │
│                                                      │
│                              [View findings]         │
└─────────────────────────────────────────────────────┘
```

Findings page populates in real-time as findings are imported (each chunk appears immediately).

**Step 4: Populated findings page**

```
┌─────────────────────────────────────────────────────────┐
│ PageShell: Findings                [Import findings] btn│
│ "28 findings across your repository"                    │
│                                                         │
│ Filters: [All severities ▾] [All statuses ▾] Sort: [Severity ▾] │
│                                                         │
│ ┌─ FindingRow ──────────────────────────────────────┐  │
│ │ ● Critical  lodash prototype pollution (CVE-...)  │  │
│ │              lodash@4.17.20 · new              [Solve] │
│ ├───────────────────────────────────────────────────┤  │
│ │ ● High      express-session fixation (CVE-...)    │  │
│ │              express@4.18.1 · new              [Solve] │
│ ├───────────────────────────────────────────────────┤  │
│ │ ● Medium    jsonwebtoken timing attack (CVE-...)  │  │
│ │              jsonwebtoken@9.0.0 · triaged  🔗  [Solve] │
│ │              ↑ PR link icon (when PR exists)       │  │
│ └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**States:**

- **Loading:** Skeleton rows (3 placeholder rows with pulse animation)
- **Empty:** EmptyState with import CTA (shown above)
- **Error:** ErrorState: "Couldn't load findings" + retry button
- **Populated:** Finding rows sorted by severity descending

### Flow 2: Repository setup (Story 3)

**Entry point:** Settings page → new "Repository" section. Also prompted during first-run onboarding if user tries to "Solve" without a repo configured.

```
┌─────────────────────────────────────────────────────┐
│ Settings                                             │
│                                                      │
│ ┌─ Repository ──────────────────────────────────┐   │
│ │                                                │   │
│ │  GitHub repository                             │   │
│ │  ┌──────────────────────────────────────────┐  │   │
│ │  │ https://github.com/galanko/cliff       │  │   │
│ │  └──────────────────────────────────────────┘  │   │
│ │  The repo Cliff will clone into workspaces   │   │
│ │                                                │   │
│ │  Personal access token                         │   │
│ │  ┌──────────────────────────────────────────┐  │   │
│ │  │ ghp_••••••••••••••••••••                 │  │   │
│ │  └──────────────────────────────────────────┘  │   │
│ │  Needs: repo, read:org, workflow permissions   │   │
│ │                                                │   │
│ │  [Test connection]   ← outline button          │   │
│ │                                                │   │
│ │  ✓ Connected — can clone, push, create PRs     │   │
│ │                                                │   │
│ │                       [Save]  ← primary button │   │
│ └────────────────────────────────────────────────┘   │
│                                                      │
│ ┌─ AI provider ─────────────────────────────────┐   │
│ │  (existing ProviderSettings component)         │   │
│ └────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Test connection states:**

- **Idle:** Button shows "Test connection"
- **Testing:** Button shows spinner + "Testing..."
- **Success:** `✓ Connected — can clone, push, create PRs` in tertiary color
- **Failure:** `✗ Connection failed: invalid token` in error color, with details

**Guard: Solve without repo configured**

If user clicks "Solve" on Findings page without a repo configured:

```
┌─────────────────────────────────────────────────────┐
│ Repository not configured                    [×]     │
│                                                      │
│ To remediate findings, Cliff needs access to       │
│ your repository so agents can analyze code and       │
│ create pull requests.                                │
│                                                      │
│          [Configure repository]  → goes to Settings  │
└─────────────────────────────────────────────────────┘
```

### Flow 3: Guided remediation pipeline (Story 4)

**Entry point:** User clicks "Solve" on a finding → workspace opens with repo cloned.

**Updated action chips (4 agents, no Owner Resolver):**

```
┌─────────────────────────────────────────────────────┐
│ Action chips bar                                     │
│                                                      │
│ [✨ Enrich finding]  [Check exposure]                │
│  ↑ highlighted       [Build plan]  [Remediate]       │
│  (suggested next)                                    │
│                                                      │
│ Highlight = bg-primary-container/30 + ring-2         │
│            ring-primary/20 + subtle pulse            │
└─────────────────────────────────────────────────────┘
```

**Suggest-next progression:**

| After this agent completes... | Next suggested action | Highlight style |
|---|---|---|
| (workspace opens) | "Enrich finding" | Highlighted + "Recommended" tooltip |
| Enricher | "Check exposure" | Highlighted |
| Exposure Analyzer | "Build plan" | Highlighted |
| Planner | "Remediate" | Highlighted + stronger emphasis (this is the hero action) |
| Remediation (PR created) | No chip highlighted. Show "Review PR on GitHub →" link in chat | — |

**Chip states:**

- **Default:** `bg-surface-container-lowest text-primary` (no border — tonal only)
- **Suggested:** `bg-primary-container/30 ring-2 ring-primary/20` + subtle scale pulse
- **Running:** Chip shows spinner, text changes to "Enriching...", disabled
- **Completed:** Check icon prefix, muted text `text-on-surface-variant`
- **Disabled:** `opacity-50 cursor-not-allowed` (e.g., can't Remediate before Plan)

### Flow 4: Structured result cards in chat (Story 5)

Each agent type gets a dedicated card layout in the chat timeline. Cards appear as assistant messages with structured content instead of raw markdown.

**Enricher result card:**

```
┌─────────────────────────────────────────────────────┐
│ (icon: auto_awesome)  ENRICHER RESULT                │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ┌──────┐                                         │ │
│ │ │ CVE  │  CVE-2024-48930                         │ │
│ │ └──────┘  lodash prototype pollution             │ │
│ │                                                   │ │
│ │ CVSS  ████████░░  8.1 High                       │ │
│ │                                                   │ │
│ │ Affected     4.17.20                              │ │
│ │ Fixed        4.17.21                              │ │
│ │ Exploit      ⚠ Public exploit available           │ │
│ │                                                   │ │
│ │ Confidence   ●●●○ High                           │ │
│ │                                                   │ │
│ │ ▸ View details (expandable: description,          │ │
│ │   references, evidence sources)                   │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Exposure result card:**

```
┌─────────────────────────────────────────────────────┐
│ (icon: auto_awesome)  EXPOSURE ANALYSIS              │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Reachability     ● Likely reachable              │ │
│ │ Environment      production                      │ │
│ │ Internet-facing  No (internal dependency)        │ │
│ │ Criticality      Medium                          │ │
│ │                                                   │ │
│ │ Import chain:                                     │ │
│ │ src/api/auth.ts → lodash.merge()                 │ │
│ │                                                   │ │
│ │ Urgency  ██████░░░░  Moderate                    │ │
│ │                                                   │ │
│ │ Confidence   ●●○○ Medium                         │ │
│ │                                                   │ │
│ │ ▸ View full analysis                             │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Planner result card:**

```
┌─────────────────────────────────────────────────────┐
│ (icon: auto_awesome)  REMEDIATION PLAN               │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Fix steps                                         │ │
│ │  1. Upgrade lodash from 4.17.20 → 4.17.21       │ │
│ │  2. Run npm install to update lockfile            │ │
│ │  3. Run test suite to verify no regressions       │ │
│ │                                                   │ │
│ │ Interim mitigation                                │ │
│ │  Validate all merge() inputs at API boundary      │ │
│ │                                                   │ │
│ │ Effort    ○ Small (single dependency bump)        │ │
│ │                                                   │ │
│ │ Definition of done                                │ │
│ │  ☐ lodash ≥ 4.17.21 in package.json              │ │
│ │  ☐ Tests pass                                     │ │
│ │  ☐ Snyk re-scan shows finding resolved            │ │
│ │                                                   │ │
│ │ Confidence   ●●●● High                           │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Card design rules (all cards):**

- Background: `bg-surface-container-lowest` (white) with `shadow-sm`
- Rounded: `rounded-2xl rounded-bl-md` (consistent with assistant messages)
- Header: Agent icon + label in `text-[10px] font-bold uppercase tracking-widest text-on-surface-variant`
- Section labels: `text-xs font-semibold text-on-surface`
- Values: `text-sm text-on-surface-variant`
- Confidence badge: colored dots (●●●○) + text label
- Expandable sections: `▸ View details` with smooth expand/collapse
- NO borders inside the card. Use spacing + tonal bg shifts for separation

### Flow 5: Remediation execution (Story 6) — the hero flow

This is the most complex interaction. It's a collaborative, multi-step process within the chat.

**Step 1: User triggers "Remediate"**

After the Planner has run and the user clicks the "Remediate" action chip (or the pipeline suggests it).

```
┌─────────────────────────────────────────────────────┐
│ PLAN APPROVAL                                        │
│ (icon: checklist)                                    │
│                                                      │
│ Before I make changes to your code, please review    │
│ the planned fix:                                     │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │  1. Upgrade lodash: 4.17.20 → 4.17.21          │ │
│ │  2. Run npm install                              │ │
│ │  3. Run full test suite                          │ │
│ │                                                   │ │
│ │  Branch: cliff/fix/cve-2024-48930-lodash       │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ You can modify this plan by typing in the chat.      │
│                                                      │
│ [Approve and start]  [Modify plan]                   │
└─────────────────────────────────────────────────────┘
```

**Interaction:** User can either click "Approve and start" or type a modification in the chat (e.g., "Also update the express package while you're at it"). The agent responds, updates the plan, and re-presents for approval.

**Step 2: Agent executing fix**

Once approved, the chat shows live progress:

```
┌─────────────────────────────────────────────────────┐
│ REMEDIATING                                          │
│ (icon: build — animated)                             │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ✓ Created branch cliff/fix/cve-2024-48930     │ │
│ │ ✓ Updated package.json (lodash: 4.17.21)         │ │
│ │ ● Running npm install...                          │ │
│ │ ○ Run test suite                                  │ │
│ │ ○ Commit and push                                 │ │
│ │ ○ Create draft PR                                 │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ The streaming text area below shows live agent        │
│ output (terminal-like, monospace font)               │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ > npm install                                     │ │
│ │ updated 1 package in 2.3s                         │ │
│ │ > npm test                                        │ │
│ │ PASS src/api/auth.test.ts (12 tests)             │ │
│ │ PASS src/utils/merge.test.ts (8 tests)█          │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Progress checklist states:**
- `✓` Completed: `text-tertiary` (green token)
- `●` In progress: `text-primary animate-pulse`
- `○` Pending: `text-on-surface-variant/40`

**Step 3: Tests passed → PR created**

```
┌─────────────────────────────────────────────────────┐
│ (icon: auto_awesome)  REMEDIATION COMPLETE           │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │                                                   │ │
│ │  ✓ Fix applied and tests passing                  │ │
│ │                                                   │ │
│ │  Files changed                                    │ │
│ │   M package.json (+1 -1)                          │ │
│ │   M package-lock.json (+12 -8)                    │ │
│ │                                                   │ │
│ │  Tests  ✓ 47 passed · 0 failed                   │ │
│ │                                                   │ │
│ │  ┌──────────────────────────────────────────┐    │ │
│ │  │ (icon: git_merge)  Draft PR #42          │    │ │
│ │  │                                           │    │ │
│ │  │ fix: lodash prototype pollution           │    │ │
│ │  │ (CVE-2024-48930)                          │    │ │
│ │  │                                           │    │ │
│ │  │ cliff/fix/cve-2024-48930 → main         │    │ │
│ │  │                                           │    │ │
│ │  │ [Review on GitHub →]                      │    │ │
│ │  └──────────────────────────────────────────┘    │ │
│ │                                                   │ │
│ │  Confidence   ●●●● High                          │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**PR card design:**
- Nested card within the result: `bg-surface-container-low rounded-xl p-4`
- Git merge icon + PR number as header
- PR title, branch info, link to GitHub
- Link styled as primary action: `text-primary font-semibold hover:underline`

**Step 4: Tests failed — collaborative recovery**

If tests fail, the agent does NOT push or create a PR. Instead:

```
┌─────────────────────────────────────────────────────┐
│ REMEDIATION — NEEDS GUIDANCE                         │
│ (icon: warning — tertiary color, NOT error)          │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ✓ Updated package.json                           │ │
│ │ ✓ Ran npm install                                │ │
│ │ ✗ Tests failed (2 failures)                      │ │
│ │                                                   │ │
│ │  FAIL src/utils/merge.test.ts                    │ │
│ │   ✗ should deep merge objects (expected ...)     │ │
│ │   ✗ should handle circular refs (timeout)        │ │
│ │                                                   │ │
│ │ The upgrade changed lodash.merge() behavior.     │ │
│ │ I can try to fix the failing tests, or you can   │ │
│ │ guide me on the right approach.                  │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ [Fix the tests]  [Let me look at the failures]       │
│                  [Undo changes]                       │
└─────────────────────────────────────────────────────┘
```

**Key UX decision:** Test failures are NOT shown as errors (red). They're shown as a collaborative checkpoint — the agent is asking for help, not reporting a crash. Use `text-tertiary` for the warning icon and calm language.

### Flow 6: Workspace sidebar updates (Stories 5, 6)

The sidebar evolves from the current 7-section layout to an MVP-appropriate layout:

**MVP sidebar sections (top to bottom):**

1. **Summary** — what + why (from enricher)
2. **Evidence** — CVE details, exploit status, versions (from enricher + exposure)
3. **Exposure** — reachability, environment, urgency (from exposure analyzer)
4. **Plan** — fix steps + definition of done (from planner)
5. **Pull request** — branch, PR link, PR state, files changed (from remediation agent) ← REPLACES "Owner" and "Ticket"
6. **Validation** — fix verdict if re-run (kept but rarely used in MVP)

**"Pull request" section — new:**

```
┌─────────────────────────────────────────────────────┐
│ PULL REQUEST                                         │
│ (10px uppercase label, same style as other sections) │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │  status   Draft PR #42                           │ │
│ │  branch   cliff/fix/cve-2024-48930             │ │
│ │  files    2 changed (+13 -9)                     │ │
│ │  tests    47 passed                              │ │
│ │                                                   │ │
│ │  [Review on GitHub →]                            │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ Before PR is created:                                │
│   "Not yet available" (italic, muted)                │
└─────────────────────────────────────────────────────┘
```

### Flow 7: Finding status progression (Story 7)

**Status badge progression:**

| Status | Badge | Trigger | Color |
|---|---|---|---|
| New | `new` | Finding imported | `bg-surface-container-high text-on-surface-variant` (neutral) |
| Triaged | `triaged` | Enricher completes | `bg-secondary-container/30 text-secondary` |
| In progress | `in progress` | Planner completes | `bg-primary-container/30 text-primary` |
| Remediated | `remediated` | PR created | `bg-tertiary-container/30 text-tertiary` |
| Closed | `closed` | User marks as merged/resolved | `bg-surface-container-high text-on-surface-variant` (neutral, completed feel) |

All badges are `px-2 py-0.5 rounded-full text-[10px] font-semibold` — consistent with existing SeverityBadge.

**Findings page row with PR link:**

When a finding has a PR, show a small GitHub icon link:

```
│ ● High  express-session fixation    remediated  🔗 #42  [Solve] │
│                                                   ↑ clickable    │
│                                          opens GitHub PR         │
```

Icon: `material-symbols-outlined: link` or custom GitHub icon, `text-primary text-sm`.

---

## States (global)

### Loading state

All pages use skeleton loading (pulse animation placeholders):

- Finding rows: 3 skeleton rows with gray blocks for title, severity, status
- Workspace: chat skeleton + sidebar skeleton
- Settings: form field skeletons

Style: `bg-surface-container-high/50 rounded animate-pulse`

### Empty state

The `EmptyState` component already exists. For MVP, it's used on:

- **Findings page (no findings):** Icon `assignment_late`, "No findings yet", "Import findings from your scanner to get started", primary CTA
- **History page (no completed workspaces):** Icon `history`, "No completed workspaces", "Solve a finding to see it here"
- **Workspace sidebar sections (not yet populated):** Italic text "Not yet available" in `text-outline-variant`

### Error state

New `ErrorState` component (similar to EmptyState but for failures):

```
┌─────────────────────────────────────────────────────┐
│                                                      │
│    (icon: error_outline — text-error)                │
│                                                      │
│    Something went wrong                              │
│    We couldn't load your findings.                   │
│    Check your connection and try again.              │
│                                                      │
│    [Retry]  ← outline button                         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

Style: Same centered layout as EmptyState. Icon in `text-error`, title in `text-on-surface font-headline font-bold`, subtitle in `text-on-surface-variant`.

Error boundaries wrap each page component. On render crash, show ErrorState with "Reload page" CTA.

### Success state

Toast notification for transient success (e.g., "Settings saved", "Finding imported"):

```
┌──────────────────────────────────────┐
│ ✓  28 findings imported successfully │
└──────────────────────────────────────┘
```

Position: bottom-right, auto-dismiss after 4s. Style: `bg-surface-container-lowest shadow-lg rounded-xl px-4 py-3`, check icon in `text-tertiary`.

---

## Responsive behavior

MVP targets desktop only (1280px+ viewport). The Serene Sentinel design system is built for desktop-first work surfaces.

- **Minimum width:** 1280px. Below this, show a "Please use a desktop browser" message
- **Sidebar:** Fixed 320px right panel. Does not collapse
- **SideNav:** Fixed 80px left. Does not collapse
- **Chat area:** Flexible width, `max-w-3xl` for message bubbles

---

## Accessibility

| Area | Requirement |
|---|---|
| Keyboard navigation | All interactive elements reachable via Tab. Action chips, buttons, form fields |
| Focus indicators | `focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2` on all interactive elements |
| Screen reader | Agent result cards use `role="region"` with `aria-label="Enricher result"`. Status badges use `aria-label` (not just color) |
| Color contrast | All text meets WCAG AA (4.5:1 for body, 3:1 for large text). Design tokens already meet this |
| Motion | Pulse animations respect `prefers-reduced-motion: reduce` |
| Forms | All inputs have visible labels (not just placeholders). Error messages use `aria-live="polite"` |

---

## Design system compliance

| Rule | Status in this spec |
|---|---|
| No-Line Rule | ✅ No `1px solid` borders anywhere. All separation via tonal shifts, spacing, shadows |
| Tonal Layering | ✅ Level 0 `surface` → Level 1 `surface-container-low` → Level 2 `surface-container-lowest` |
| Ghost Borders | ✅ Only used for cards: `shadow-sm` or `shadow-[0_0_0_1px_rgba(var(--outline-variant),0.15)]` |
| Sentence case | ✅ All labels, headers, buttons in sentence case |
| Text color | ✅ `on-surface` for primary text, `on-surface-variant` for secondary. Never `#000` |
| Primary color | ✅ `#4d44e3` for actions, focus, highlights |
| Background | ✅ `#f8f9fa` page background |
| Headlines | ✅ Manrope 600-800 |
| Body/labels | ✅ Inter 400-600 |
| Icons | ✅ Google Material Symbols Outlined only |
| Light mode | ✅ Light mode only |

---

_This UX spec follows the Cliff design workflow. After CEO approval, it moves to the architect team for implementation planning via `/architect`._
