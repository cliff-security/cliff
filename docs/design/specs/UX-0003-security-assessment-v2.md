# UX-0003: Security assessment v2

**PRD:** docs/product/prds/PRD-0003-security-assessment-v2.md (rev. 2, 2026-04-25)
**Status:** Draft · rev. 2 amended 2026-04-25
**Date:** 2026-04-16, revised 2026-04-25
**Canonical visual reference (rev. 2):** `frontend/mockups/claude-design/` — the Claude design hand-off (`README.md`, `surfaces/*.jsx`, `colors_and_type.css`, `PRD-0003 design.html`)
**Implementation plan:** docs/architecture/plans/IMPL-0003-security-assessment-v2.md (rev. 2)
**Architecture:** ADR-0027 (unified findings), ADR-0028 (subprocess-only scanners), ADR-0029 (warning token), ADR-0032 (rev. 2 dashboard payload)

---

## Rev. 2 amendment (2026-04-25)

The original UX spec below was produced by `/ux-designer` against PRD-0003 rev. 1 and is preserved as historical record. For v0.2 implementation, **the canonical visual reference is the Claude design hand-off staged at `frontend/mockups/claude-design/`** — it covers the same six surfaces with higher fidelity, clearer state vocabulary, and a stricter mapping to Serene Sentinel tokens.

When rev. 1 of this spec and the Claude design hand-off disagree on a visual decision, the hand-off wins for v0.2. The conflicts of note are documented in `frontend/mockups/claude-design/IMPL-DELTA.md`.

**Surface mapping** (rev. 1 spec → rev. 2 canonical reference):

| Surface | Rev. 1 mockup (historical) | Rev. 2 canonical reference (use this) |
|---------|---------------------------|---------------------------------------|
| Report card with grouped posture | `frontend/mockups/html/prd-0003-report-card-posture.html` | `frontend/mockups/claude-design/surfaces/report-card.jsx` (variation A) |
| Assessment progress with scanner stages | `frontend/mockups/html/prd-0003-assessment-progress.html` (frames 3.1–3.3) | `frontend/mockups/claude-design/surfaces/assessment-progress.jsx` |
| Assessment-complete summary | `frontend/mockups/html/prd-0003-assessment-progress.html` (frame 3.5) | `frontend/mockups/claude-design/surfaces/assessment-complete.jsx` (variation A) |
| Onboarding step 3 | `frontend/mockups/html/prd-0003-assessment-progress.html` (frame 3.4) | `frontend/mockups/claude-design/surfaces/onboarding-step3.jsx` |
| Completion progress card | covered in report card mockup | `frontend/mockups/claude-design/surfaces/completion-progress.jsx` |
| Shareable summary card | minor text update | `frontend/mockups/claude-design/surfaces/share-card.jsx` |

**Decisions that shifted in rev. 2** (covered in detail by ADR-0032):

1. **Tool identity payload.** A single `tools[]` array drives the `Scanned by` row and the `ToolPillBar` everywhere it appears. Each entry carries `{id, label, version, icon, state, result?}` — the `result` tail is what powers the "Trivy 0.52 · 7 findings" rendering on the report-card hero.
2. **Posture-check vocabulary.** Four states (`pass | fail | done | advisory`) replace the rev. 1 binary pass/fail. The `done` state shows a `Draft PR ↗` link to the GitHub PR an Cliff agent opened — preserving the brand moment that pass/fail collapsed.
3. **Criteria with labels.** The completion-progress card reads its 10 criteria from a labeled `criteria[]` payload, not a static frontend label map.
4. **Severity color.** Medium severity uses the `warning` token family (ADR-0029), not `tertiary`. The Claude design hand-off's `SeverityChip` defaulted medium to tertiary; that mapping is overridden by ADR-0029 in our codebase.
5. **Interstitial gate.** The assessment-complete summary is gated by a server-side `summary_seen_at` flag on the `assessment` row, not by a `?assessment=complete` URL trick.

The rest of the rev. 1 spec below is intact. Read it for the breadth of the change (component-level intent, copy decisions, accessibility considerations); read the Claude design hand-off for the specific visual implementation.

---

## Screen inventory

PRD-0003 touches five existing screens, adds one new transitional screen, and introduces no new pages. Every change is an evolution of PRD-0002's layout — Alex's mental model stays the same.

| # | Screen | What changes | Mockup |
|---|--------|-------------|--------|
| 1 | **Report card — posture section** | Expands from flat list to 4 grouped categories (CI supply chain, collaborator hygiene, code integrity, repo configuration). Adds "scanned by" metadata. Advisory vs pass/fail visual distinction. Generator CTAs for SHA pinning + CODEOWNERS | `frontend/mockups/html/prd-0003-report-card-posture.html` |
| 2 | **Assessment progress** | Steps change from 5 homebrew stages to scanner-specific stages with tool names. Tool pills show which scanners are running. Active step expands with progress bar and detail text | `frontend/mockups/html/prd-0003-assessment-progress.html` (frames 3.1–3.3) |
| 3 | **Assessment complete summary** | **NEW.** Interstitial shown after assessment finishes, before the report card. Summarizes findings count, posture results across 4 areas, quick wins Cliff can auto-fix, and grade preview. Bridges the gap so Alex isn't surprised by 15 checks in 4 categories | `frontend/mockups/html/prd-0003-assessment-progress.html` (frame 3.5) |
| 4 | **Onboarding Step 3** | Copy updated to reference Trivy/Semgrep by name. "Powered by" tool pills added. Preview steps expanded to 4 | `frontend/mockups/html/prd-0003-assessment-progress.html` (frame 3.4) |
| 5 | **Completion progress card** | Criteria count changes from 5 to 10. Grade ring recalibrated | Component update, covered in report card mockup |
| 6 | **Shareable summary card** | Criteria count in text updated. "Scanned by" line added | Minor text update |

---

## Component breakdown

### Existing components to modify

| Component | Location | Changes |
|-----------|----------|---------|
| `PostureCheckItem` | `components/dashboard/PostureCheckItem.tsx` | Add `category` grouping prop. Expand `GENERATOR_CHECKS` set to include `sha_pinning` and `codeowners`. Add advisory state visual (already exists as `advisory` status — just needs new check names) |
| `AssessmentProgressList` | `components/dashboard/AssessmentProgressList.tsx` | Replace 5 hardcoded steps with scanner-specific steps from backend. Steps are now dynamic (varies by which scanners are selected for the repo) |
| `DashboardPage` | `pages/DashboardPage.tsx` | `CRITERIA_TOTAL` changes from 5 to 10. `PostureCard` section restructured into grouped categories with category headers. Add "scanned by" metadata line |
| `CompletionProgressCard` | `components/dashboard/CompletionProgressCard.tsx` | `criteriaTotal` now 10. Pill meter recalibrated |
| `GradeRing` | `components/dashboard/GradeRing.tsx` | No visual change — just receives new values (10 criteria) |
| `StartAssessment` | `pages/onboarding/StartAssessment.tsx` | `STEPS` array updated: 3 steps become 4 (detect → Trivy → posture → descriptions). Copy references scanner names |

### New components

| Component | Purpose |
|-----------|---------|
| `PostureCategoryGroup` | Groups posture checks under a category header (CI supply chain, collaborator hygiene, code integrity). Renders a heading + list of `PostureCheckItem` children |
| `ScannedByLine` | Metadata pill showing which tools ran and their versions. E.g., "Scanned by: Trivy 0.52 · Semgrep 1.70" |
| `ToolPillBar` | Row of tool identity pills shown during assessment progress and on the summary screen. Each pill shows tool name + version + state (pending/active/done/skipped). Active pill pulses subtly. Done pill shows check icon. Skipped pill shows strikethrough |
| `AssessmentSummary` | Interstitial screen shown once after assessment completes, before the report card. Three summary cards (vulnerabilities, posture, quick wins) + grade preview + "View your report card" CTA. Bridges the transition so Alex knows what to expect on the report card |

---

## Interaction flows

### Flow 1: Assessment progress (Story 1 + Story 5)

The user either triggers an assessment from onboarding Step 3 or via "Re-assess" on the report card.

**Step 1 — Assessment starts**
The dashboard switches to `AssessmentProgressList` (same pattern as PRD-0002). The header reads "Assessing your repository" with the radar spinner.

**Step 1b — Tool pill bar appears**
Below the header, a `ToolPillBar` shows which tools will run this assessment: "Trivy 0.52", "Semgrep 1.70", "15 posture checks". The currently-active tool pill pulses subtly (`animate-pulse-subtle`) in `primary-container/40`. Completed tool pills show a check icon in `text-tertiary`. Skipped pills show strikethrough text. This gives Alex a persistent, at-a-glance view of the tools backing the assessment.

**Step 2 — Dynamic scanner steps with expanded active step**
Instead of 5 fixed steps, the list shows steps derived from the backend response:

| Step key | Label | When shown |
|----------|-------|-----------|
| `detect` | Detecting project type | Always |
| `trivy_vuln` | Scanning dependencies with Trivy | Always (Phase 1a) |
| `trivy_secret` | Checking for committed secrets | Always |
| `semgrep` | Scanning code with Semgrep | Phase 1b, when code files detected |
| `govulncheck` | Analyzing Go call graph | Phase 1b, when go.mod detected |
| `posture` | Checking repo posture | Always |
| `descriptions` | Writing plain-language descriptions | Always |

Each step progresses through: pending → running → done. The **active step expands** into a card (`rounded-2xl bg-surface-container-lowest p-4`) showing: spinner + label + percentage, a progress bar underneath, and a detail line describing what's happening (e.g., "Checking 312 dependencies across npm and pip ecosystems..."). Completed steps show result metadata in a pill badge (e.g., "12 findings", "npm + Python detected", "0 found").

**Step 3 — Assessment complete summary (NEW)**
Instead of jumping directly to the report card, Alex sees an **assessment complete interstitial** (`AssessmentSummary` component). This screen:

1. Shows a success icon (green check in `tertiary-container/40`) + "Assessment complete" heading
2. Displays the `ToolPillBar` with all tools in their final state (done/skipped)
3. Shows three summary cards side-by-side:
   - **Vulnerabilities**: total count + severity breakdown + which tools found them
   - **Posture**: X of 15 pass + names the 4 categories (CI supply chain, collaborator hygiene, code integrity, repo configuration) — this is the key moment that primes Alex for the grouped posture card
   - **Quick wins**: count of items Cliff can fix automatically, with short labels
4. Shows a **completion preview**: "8 of 10 criteria met — grade B" with a mini grade ring
5. Single CTA: "View your report card →"

**Why this matters:** Without this screen, Alex goes from a progress list to a dashboard with 15 checks in 4 categories they've never seen before. The summary introduces the categories, sets expectations for the grade, and highlights the quick wins — so the report card feels like a familiar expansion, not a surprise.

This screen is shown:
- After the **first** assessment completes (onboarding flow)
- After a **re-assessment** if the posture check count changed
- NOT on subsequent dashboard visits (the report card loads directly)

**Step 4 — Report card**
Alex clicks "View your report card" and lands on the full dashboard. The "scanned by" line appears in the hero section. The posture section's 4 categories match what they just saw on the summary.

### Flow 2: Report card posture section (Stories 2-4, 6)

**What changes:**
The posture card currently shows a flat list of failures + a summary count. PRD-0003 restructures this into categorized groups.

**Layout — grouped posture checks:**

```
┌─ Repo posture ─────────────────────────────────────────┐
│  12 of 15 checks pass                                  │
│                                                        │
│  CI supply chain                                       │
│  ✓ Actions pinned to SHA                               │
│  ✗ Trusted action sources          [details + fix]     │
│  ℹ Workflow trigger scope          [advisory]          │
│                                                        │
│  Collaborator hygiene                                  │
│  ✓ No stale collaborators                              │
│  ✗ Broad team permissions          [advisory]          │
│  ✓ Default branch permissions                          │
│                                                        │
│  Code integrity                                        │
│  ✓ Secret scanning enabled                             │
│  ✗ Code owners file missing        [Generate + PR]     │
│  ℹ Signed commits                  [advisory]          │
│  ✓ Dependabot configured                               │
│                                                        │
│  Repo configuration (from PRD-0002)                    │
│  ✓ Branch protection enabled                           │
│  ✓ SECURITY.md exists                                  │
│  ✓ No secrets in code                                  │
│  ✓ Signed releases                                     │
└────────────────────────────────────────────────────────┘
```

**Category headers** use `text-xs font-bold uppercase tracking-wide text-on-surface-variant` — the same "small caps label" pattern used in the hero section for "Security grade". This gives them enough presence without competing with the card's main heading.

**Advisory checks** show the `info` Material Symbol icon in `text-on-surface-variant` (muted, non-alarming). They are visually distinct from both pass (green check) and fail (red error). The advisory row doesn't expand and has no CTA — it's informational. Tooltip or inline text explains why this isn't blocking.

**Generator CTAs** appear on failing checks that Cliff can auto-fix:

| Check | CTA label | Action |
|-------|-----------|--------|
| Actions not pinned | "Pin actions to SHA" | Generates a PR pinning all actions to current SHAs |
| CODEOWNERS missing | "Generate code owners" | Generates CODEOWNERS from git blame heuristic |
| Dependabot missing | "Configure Dependabot" | Generates `.github/dependabot.yml` (carried from PRD-0002) |
| SECURITY.md missing | "Generate SECURITY.md" | Same as PRD-0002 |

Each CTA is a primary-style pill button: `bg-primary text-on-primary rounded-full px-4 py-2 text-sm font-semibold`. On click → navigates to a workspace where the agent generates the file and opens a draft PR.

**"Scanned by" line** sits below the hero section, right-aligned or below the subtitle. Uses `text-xs text-on-surface-variant` with tool icons or just text: "Scanned by: Trivy 0.52 · Semgrep 1.70". Subtle, not prominent — it's trust metadata, not a headline.

### Flow 3: Onboarding Step 3 update (Story 5)

**Current copy (PRD-0002):**
- Step 1: "Clone and parse your repo"
- Step 2: "Check known vulnerabilities"
- Step 3: "Run posture checks"

**Updated copy (PRD-0003):**
- Step 1: "Detect your project type" — "We scan for lockfiles, config files, and language markers to pick the right tools automatically." (~10 s)
- Step 2: "Scan with Trivy" — "Industry-standard vulnerability scanner. Checks dependencies, secrets, and misconfigurations across all ecosystems." (~60 s)
- Step 3: "Check repo posture" — "15 security checks covering CI supply chain, collaborator hygiene, and code integrity." (~30 s)
- Step 4: "Write plain-language descriptions" — "Our AI translates scan results into clear, actionable summaries." (~60 s)

The intro paragraph updates to: "We'll scan your repository using industry-standard security tools (Trivy, Semgrep) and run 15 posture checks on your repo's security configuration. This usually takes 2-5 minutes."

### Flow 4: Completion criteria expansion (Story 6)

The `CompletionProgressCard` currently shows a pill meter with 5 slots. It now shows 10.

**Visual change:** The pill meter component (`CriteriaMeter`) already accepts `criteriaTotal` as a prop. Changing from 5 to 10 means each pill segment is narrower. To prevent the meter from looking cluttered at 10, we shift from individual pills to a continuous progress bar with tick marks at each criterion:

```
Progress: ████████░░  8/10 criteria met
```

This is a cleaner visual at higher counts while keeping the same semantics: filled = met, empty = remaining.

The `countCriteriaMet` function in `DashboardPage.tsx` expands from 5 boolean checks to 10:

1. SECURITY.md present
2. Dependabot/Renovate configured
3. No critical vulns
4. No high-severity vulns (NEW — was not separate before)
5. Branch protection enabled
6. No secrets detected
7. CI actions pinned to SHA (NEW)
8. No stale collaborators (NEW)
9. Code owners file exists (NEW)
10. Secret scanning enabled (NEW)

Grade ring: A = 10/10, B = 8-9/10, C = 6-7/10, D = 4-5/10, F = 0-3/10. Same letter grade ring component, new breakpoints.

---

## States

### Assessment progress

| State | How it looks |
|-------|-------------|
| **Loading** | Radar spinner in `primary-container` circle. "Assessing your repository" heading. Tool pill bar shows all tools in pending state. Step list with all items as small gray dots |
| **In progress** | Active tool pill pulses. Active step expands into card with progress bar + detail text. Previous steps show green check + result metadata pills. Remaining steps show gray dots |
| **Scanner skipped** | Skipped tool pill shows strikethrough. Skipped step shows warning icon + "skipped" badge. Info callout at bottom explains why. Assessment continues |
| **Complete** | All steps show green check. Transitions to **assessment summary interstitial** (not directly to report card) |
| **Error — fatal** | If clone fails or no scanners can run: error state with retry button. Same `ErrorState` component pattern |

### Assessment summary (NEW)

| State | How it looks |
|-------|-------------|
| **Default** | Success icon + "Assessment complete" heading. Tool pill bar (all done). Three summary cards (vulnerabilities, posture, quick wins). Grade preview. "View your report card" CTA |
| **Zero findings** | Vulnerabilities card shows "0" with "No vulnerabilities found" copy. Posture and quick wins still show. This is a happy path |
| **All posture passing** | Posture card shows "15 of 15 pass" in green. Quick wins card says "Nothing to fix — all checks pass" |
| **Scanner skipped** | Tool pill bar reflects the skipped scanner. Vulnerabilities card notes which tool was skipped: "Scanned by Trivy only — Semgrep not available" |

### Report card posture section

| State | How it looks |
|-------|-------------|
| **All passing** | All items show green check. No CTAs. Summary: "15 of 15 checks pass" |
| **Mixed** | Pass items are compact (1-line). Fail items expand with description + optional CTA. Advisory items show info icon, muted text |
| **Pending check** | If a check couldn't run (e.g., missing PAT scope): shows `help` icon in `text-outline` with "Unable to verify — additional permissions needed" |
| **Generator running** | CTA button shows spinner + "Opening…" text. Disabled state. On success, navigates to workspace |

### Posture check item states (updated)

| Status | Icon | Color | Text weight | CTA |
|--------|------|-------|-------------|-----|
| `pass` | `check_circle` | `text-tertiary` | `font-medium text-on-surface` | None |
| `fail` | `error` | `text-error` | `font-semibold text-on-surface` | Generator button if supported |
| `advisory` | `info` | `text-on-surface-variant` | `text-on-surface-variant` | None — informational only |
| `pending` | `help` | `text-outline` | `text-on-surface-variant` | None — "unable to verify" note |

---

## Responsive behavior

**Desktop (>1024px):** Report card uses the existing `grid-cols-[1fr_340px]` layout. Posture card is in the left column alongside vulnerabilities card (2-column grid). Category groups stack vertically within the posture card.

**Tablet (768-1024px):** Posture and vulnerabilities cards stack (1 column). Category groups remain vertical. Generator CTAs stack below the check text on narrow widths (already handled by `sm:flex-row` pattern).

**Mobile (<768px):** Full-width single column. Assessment progress list becomes the full-screen experience (already works this way). Posture category groups maintain their structure — each is a self-contained vertical list.

---

## Accessibility

| Aspect | Implementation |
|--------|---------------|
| **Semantic structure** | Category groups use `<section>` with `<h4>` headings. Posture list uses `<ul role="list">`. Each item is `<li>` |
| **ARIA labels** | Assessment progress: `aria-label="Assessment in progress"` (existing). Posture section: `aria-label="Repository posture checks"` |
| **Status announcement** | When assessment step changes, use `aria-live="polite"` region to announce "Step complete: Scanning dependencies with Trivy" |
| **Advisory vs fail** | Advisory items include `aria-label` clarifying they're informational: "Signed commits — advisory, not required for completion" |
| **Color independence** | Icons + text labels for all states. Never rely on color alone (existing pattern, maintained) |
| **Keyboard navigation** | Generator CTA buttons are standard `<button>` elements with focus-visible ring |
| **Contrast** | All text meets WCAG AA (4.5:1). Advisory text at `text-on-surface-variant` (#586064) on `surface-container-low` (#f1f4f6) = 4.8:1 ✓. Advisory pill badge text uses full-opacity `text-on-surface-variant` (not /70) to guarantee AA compliance |
| **Reduced motion** | All animations (`animate-pulse-subtle` on tool pills, `animate-spin` on progress spinners) must be disabled via `@media (prefers-reduced-motion: reduce)`. WCAG 2.1 AA §2.3.3. Mockups include the media query |

---

## Design system compliance

| Rule | Status | Notes |
|------|--------|-------|
| No-Line Rule | ✅ Pass | Category separation uses `space-y` and tonal shifts, not borders |
| Tonal Layering | ✅ Pass | Category headers on `surface-container-low`, check items on same. Fail items use `primary-container/25` bg |
| Ghost Borders | ✅ Pass | No borders introduced |
| Sentence case | ✅ Pass | All labels, headings, buttons in sentence case |
| Text color | ✅ Pass | No `#000000`. All text uses design tokens |
| Primary color | ✅ Pass | CTAs use `bg-primary`, focus states use `primary` |
| Background | ✅ Pass | `surface` base, `surface-container-low` cards |
| Headlines font | ✅ Pass | Manrope for all headings |
| Body/labels font | ✅ Pass | Inter for all body text |
| Icons | ✅ Pass | Google Material Symbols Outlined only |
| Light mode | ✅ Pass | No dark mode variants |

---

## Mockup reference

Two HTML mockup files demonstrate the key visual changes:

1. **`frontend/mockups/html/prd-0003-report-card-posture.html`** — The updated report card with grouped posture categories, advisory indicators, generator CTAs, and "scanned by" metadata
2. **`frontend/mockups/html/prd-0003-assessment-progress.html`** — The assessment progress experience with scanner-specific steps showing Trivy/Semgrep/posture stages

---

_This UX spec follows the Cliff product workflow. After CEO approval, it moves to `/architect` for implementation planning._
