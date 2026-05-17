# UX-0002: From zero to secure

**PRD:** `docs/product/prds/PRD-0002-earn-the-badge.md`
**Gallery:** `frontend/mockups/html/earn-the-badge-gallery.html` (self-contained, open in any browser)
**Status:** Revised 2026-04-15 — awaiting CEO review
**Date:** 2026-04-14 (original) / 2026-04-15 (revisions 3 and 4)
**Designer:** UX team

---

## Revision note (2026-04-15)

PRD-0002 was scoped down on 2026-04-15: the public "Secured by Cliff" README PR is deferred to v1.2, and live OpenSSF Scorecard API integration is deferred as well. v1.1 ships an in-app completion ceremony and a user-controlled shareable summary card, plus a static info-line pointing to Scorecard as an independent third-party standard.

Frames affected: 2.2 (report card relabels "Badge preview" → "Completion progress" and gains a Scorecard info-line), 5.1 (celebration reframed as "Security complete" with download / copy-text / copy-markdown actions instead of an Add-to-README CTA), 5.2 (replaced — now a "Shareable summary card · three actions" panel rendered on the same page after the celebration, no modal, no PR), 6.1 (aside relabels "Active badge" → "Security complete" and drops the freshness band), 6.2 (banner reframed — no "your badge is still valid on your README" promise, since Cliff never wrote one).

Frames 1.0–1.5, 2.1, 3.1–3.2, and 4.1 are unchanged — the onboarding flow, assessment progress, plain-language findings, and posture guidance all ship as designed.

---

## Narrative

Alex is a Node.js library maintainer. They've never run a security scanner. They land on Cliff, walk a three-step onboarding, watch a calm progress view scan their repo, land on a report card that tells them in plain English what's broken, solve the vulnerabilities one workspace at a time, and when the last criterion flips to pass they reach a quiet celebration and a shareable summary card they can download, tweet, or ignore. Cliff never modifies their README.

Every screen reinforces the Serene Sentinel posture: calm authority, editorial layout, the UI never shouts. The grade is a reward, not a scolding. The completion ceremony is a receipt for the work done, never a gate held over the user's head — and the share artifact is theirs to use on their own terms.

## Screen inventory

| # | Screen | Story | Purpose |
|---|--------|-------|---------|
| 1.0 | Welcome | 1 | Introduces Cliff with a single "Get started" CTA — no fork in the road |
| 1.1 | Connect project — default | 1 | Two fields: repo URL + PAT, with scope explanation |
| 1.1a | "How to create a token" dialog | 1 | Modal over dimmed/blurred wizard, 5-step walkthrough, deep-link to `github.com/settings/tokens` |
| 1.2 | Connect project — error | 1 | Specific, actionable error for missing `repo` scope |
| 1.3 | Connect project — verified | 1 | Compact success card: repo name, visibility, default branch, verified permissions |
| 1.4 | AI configuration | 1 | Provider picker (3 cards), API key, optional model, local-first reassurance |
| 1.5 | Start assessment | 1 | Three-step preview of what will happen and how long |
| 2.1 | Assessment running | 2 | Step-by-step progress list with counts — transparency replaces anxiety |
| 2.2 | Report card — grade C | 2 | Hero grade ring + completion-progress meter + two-column vulns/posture summary + Scorecard info line |
| 3.1 | Findings queue · plain rows | 3 | Headline in plain English, technical metadata relegated to a monospace line |
| 3.2 | Finding detail · plain + technical | 3 | Full plain-language body + expandable technical details block |
| 4.1 | Posture tab · expanded guidance | 4 | Passing checks compact, failing checks expand with "Cliff can create this" action |
| 5.1 | Completion · celebration | 5 | 3-second confetti, scaled-up shield SVG, grade A, "Security complete" headline, three share actions |
| 5.2 | Shareable summary · three actions | 5 | Rendered 1200×630 summary card preview + download image / copy text / copy markdown — no modal, no PR |
| 6.1 | Dashboard · returning user | 6 | Completion-status aside (no freshness band), headline summary, recent activity list |
| 6.2 | Re-assess · new finding | 6 | Diff summary since last check, completion-status banner (not badge banner), one-button next action |

All 15 frames are drawn in the gallery file in order.

## Component breakdown

### New components to build

| Component | Used in | Description |
|-----------|---------|-------------|
| `OnboardingShell` | 1.0–1.5 | Fixed-width centered column, 3-bar step progress, back button, shared paddings |
| `TokenHowToDialog` | 1.1a | Modal with scrim + blurred backdrop, 5-step walkthrough, vault reassurance footer, deep-link CTA to GitHub tokens page |
| `StepProgress` | 1.1–1.5 | Three-segment progress bar with label and "Step X of 3" |
| `ConnectionResultCard` | 1.3 | Compact 3-column verified metadata card (visibility, branch, permissions) |
| `InlineErrorCallout` | 1.2 | `error-container/20` rounded panel with icon + title + body + deep-link |
| `ProviderCard` | 1.4 | Selectable tile in a 3-column grid; active state uses `ring-2 ring-primary` |
| `AssessmentProgressList` | 2.1 | Ordered list of stages with done/running/pending states — mirrors agent activity pattern |
| `GradeRing` | 2.2, 6.1 | Conic-gradient ring with letter grade and "N of 5" |
| `CompletionProgressCard` | 2.2, 6.1 | Shield SVG (reduced opacity when incomplete) + five-pill criteria meter + "N criteria met · M remaining" |
| `CriteriaMeter` | 2.2, 5.1 | Five horizontal pills filling left-to-right as criteria pass |
| `ScorecardInfoLine` | 2.2 | Single-sentence static info card pointing to OpenSSF Scorecard as an independent third-party standard. External link only, no API call |
| `FindingRowPlain` | 3.1 | Plain-language headline + 1-line practical description + monospace tech line |
| `FindingDetail` | 3.2 | Editorial layout: chip row, headline, plain-language body, collapsible `TechnicalDetailsPanel` |
| `PostureCheckItem` | 4.1, 2.2 | Three states: passing (compact), info (compact muted), failing (expanded with action + preview) |
| `GenerateFilePreview` | 4.1 | Inline preview row: icon + filename + line count + "Preview" link + primary CTA |
| `CompletionCelebration` | 5.1 | Tinted gradient backdrop + animated `ConfettiLayer` + scaled `ShieldSVG` + "Security complete" headline. Single filled primary CTA ("Download summary image") + two subordinate text-link actions below (Copy text summary, Copy markdown) separated by a ghost divider. Full action panel lives on 5.2 |
| `ConfettiLayer` | 5.1 | 30–40 positioned particles, CSS keyframe fall, 3s total, no sound |
| `ShieldSVG` | 5.1, 5.2, 6.1 | Custom vertical-shield SVG component: indigo fill, ghost border, SECURED text, checkmark, "completed" date |
| `ShareableSummaryCard` | 5.2 | 1200×630 renderable card component (PNG export): repo name, completed date, vulns fixed, posture checks, PRs merged, grade. Rendered via HTML-to-canvas or similar — no external URL. Uses the sanctioned gradient exception (primary → tertiary). All white text at ≥rgba(255,255,255,0.92) to meet AA contrast |
| `SummaryActionPanel` | 5.2 | Three action tiles sharing the same pattern: header + preview block (file metadata for Download, plain text for Copy text, markdown for Copy markdown) + action button. No modal; lives on the same page as the celebration |
| `CompletionStatusCard` | 6.1 | Aside card with shield, grade, "Last assessed N days ago", re-assess CTA. The shield is a `<button>` that re-opens the summary card — `focus-visible` ring, `hover:scale-105`, screen-reader label, "Tap for summary" micro-hint that fades in on hover. One primary CTA + one secondary link only; no freshness band |
| `AssessmentDiffList` | 6.2 | Three-row list: new, unchanged, regressed — with + / = / 0 markers |

### Existing components to reuse

| Component | Where |
|-----------|-------|
| `PageShell` | Dashboard, Findings, posture |
| `SeverityBadge` | Findings queue rows, finding detail chip |
| `ActionButton` (primary / outline) | All primary CTAs |
| `EmptyState` | "Queue is clear" post-remediation |
| `Markdown` | Finding plain descriptions, PR preview |
| `SideNav` · `TopBar` | Global chrome |

### Components removed / repurposed

- `AddBadgeDialog` and `FreshnessCard` from the original spec are **removed** — both were tied to the deferred public-badge PR flow.
- `BadgePreviewCard` is renamed to `CompletionProgressCard`. Same visual treatment (shield SVG + criteria meter); the word "badge" is dropped from the label.
- `BadgeEarnedCelebration` is renamed to `CompletionCelebration`.
- The shield SVG itself is preserved — it remains the visual emblem of security completion inside Cliff and on the downloaded summary card. What's removed is the workflow that would have placed the shield on the user's README via a PR.

All new screens slot into the existing app chrome. The dashboard becomes a new top-level page; the onboarding wizard is a dedicated full-page route that bypasses the usual nav.

## Interaction flows

### Story 1 — onboarding

1. App boots → `/onboarding/welcome` if no repo and no completed onboarding flag → screen 1.0
2. Click "Get started" → 1.1. Click "I already have findings" → skip directly to `/findings` empty-state with import prompt
3. Fill repo URL + PAT → click "Test connection". Backend validates in under 2s.
    - If the token is missing the `repo` scope → 1.2 (error callout, input keeps ring-2 ring-error/40, no data lost)
    - If the token is valid → 1.3 (verified card replaces the form, "Change" button reopens the form)
4. Click "Continue to AI setup" → 1.4. Pick provider, enter key, "Test and continue" → 1.5
5. Click "Start assessment" → 2.1 (redirect to `/dashboard?assessment=running`)

### Story 2 — assessment and report card

1. `/dashboard?assessment=running` shows 2.1, polls backend every 1s (or SSE), flipping list items as stages complete
2. When assessment finishes → 2.2. Stage list fades out, grade ring scales in from 0 to 60% (400ms spring)
3. "Start fixing" → navigates to `/findings?sort=severity`
4. Import findings → opens the existing import modal (v1.0 behavior preserved)
5. Re-assess → returns to 2.1 progress view

### Story 3 — plain language

1. Findings queue default sort is severity desc. Each row shows plain-language headline as primary
2. Click a row → `/findings/:id` → 3.2
3. Click "Technical details" disclosure → expands in-place (no navigation)
4. Click "Solve" → creates workspace, navigates to `/workspace/:id` (v1.0 behavior)

### Story 4 — posture

1. Dashboard → click "See all checks" (implicit on a "posture" card CTA) or navigate to `/dashboard/posture`
2. Passing checks stay compact (1-line chips). Info (advisory) checks render muted
3. Failing checks render expanded with fix guidance. SECURITY.md and Dependabot include a primary "Generate and open PR" CTA
4. Click "Preview" on a generated file → opens the dialog with the rendered markdown/yaml
5. Click "Generate and open PR" → ephemeral workspace runs a single-shot template agent, opens a draft PR on GitHub, inline card flips to "PR #47 open · awaiting merge"

### Story 5 — completion ceremony

1. Any action that flips the final criterion from fail to pass triggers the celebration state (5.1) on the dashboard. No modal — the dashboard itself enters the celebration state
2. Confetti runs for 3s then fades. Gradient backdrop stays for another 1s then relaxes back to Level 0
3. The celebration offers **one primary action** ("Download summary image") and **two subordinate text-link actions** ("Copy text summary", "Copy markdown") below it. The full side-by-side action panel lives on 5.2 just below the celebration — 5.1 is the emotional peak, not a full action menu
4. Below the celebration, the `ShareableSummaryCard` is rendered in-place (5.2) — no dialog, no separate step. Three equal-pattern action tiles (Download / Copy text / Copy markdown) each show a preview block (filename+dimensions for Download, plain-text for Copy text, markdown for Copy markdown) plus an action button
5. Cliff does **not** create any PR to the user's repo as part of this flow. The markdown the user copies is for them to paste themselves, if they choose
6. The user can return to the summary card later by clicking the shield in the dashboard aside — the shield is the affordance (focus-visible ring, hover scale, screen-reader label "Re-open shareable summary card"). No extra text link clutters the aside

### Story 6 — returning and re-assess

1. On app open after completion was reached, `/dashboard` renders 6.1 with the `CompletionStatusCard` aside. The aside shows the shield, grade, "Last assessed N days ago", and the Re-assess CTA. **No freshness band** — since Cliff isn't promising anything to a public audience, there's nothing to go "stale"
2. "Re-assess now" → 2.1 progress view → either:
    - Nothing changed → returns to 6.1 with updated "Last assessed" date + a subtle "Everything still checks out" toast
    - New findings → 6.2 with the diff list and the completion-status banner (reassurance-first: "You're still at completion — for now")

## States

| State | Visual |
|-------|--------|
| **Loading** | Existing spinner pattern: `border-primary/30 border-t-primary rounded-full animate-spin`. For assessment: step-by-step list (2.1) instead of a single spinner |
| **Empty** | `EmptyState` component; "Queue is clear" after remediation; "No history yet" in assessment history |
| **Error — connection** | 1.2 pattern: `error-container/20` callout, keeps user input, opens a deep-link to the fix |
| **Error — agent failure** | Inline in the posture card: "Couldn't verify — GitHub API rate limit. Retry in 12 minutes." (uses `text-error`, not alarmist) |
| **Success — transient** | Bottom-anchored toast with `bg-surface-container-lowest`, `shadow-lg`, auto-dismiss 4s. Badge PR opened = dashboard banner |
| **Success — permanent** | Verified card (1.3), green tertiary check on posture items, grade upgraded |
| **Celebration** | 5.1 — confetti layer, gradient backdrop, scaled shield, "Security complete" headline |
| **Completion holding** | 6.1 aside — shield + grade + "Last assessed N days ago" + re-assess CTA. No freshness band, no stale state |
| **Completion at risk** | 6.2 banner — calm tertiary accent bar, "You're still at completion — for now", reassurance-first copy, finding card below carries the severity signal |

## Responsive behavior

- **≥1280px:** Two-column report card, onboarding content sits in a centered 576px column with generous side padding
- **768–1279px:** Report card collapses to stacked cards; two-column sections become single-column; onboarding is full-width with max-w-xl
- **<768px:** Full-width single column; grade ring reduces to 112px; confetti uses fewer particles (20) for perf; side nav collapses to a bottom tab bar (existing pattern); dialogs become full-screen sheets

## Accessibility

- All interactive elements reach `focus-visible: ring-2 ring-primary/40 ring-offset-2 ring-offset-surface` — closes the existing audit gap
- Color is never the sole signal: pass/fail states always pair their token color with an icon and a text label
- The decorative shield on the summary card (5.2 preview) has `role="img"` and `aria-label="Cliff security summary shield"`
- The interactive shield on the 6.1 dashboard aside is a real `<button>` with `aria-label="Re-open shareable summary card"` and its own focus ring. Hover affordance ("Tap for summary" micro-hint) fades in visually but the button label is always present for assistive tech
- The celebration animation respects `prefers-reduced-motion`: confetti disappears, grade ring fades in instead of scaling, background tint still applies. Shield hover-scale on 6.1 also collapses to a simple background shift under reduced-motion
- Plain-language descriptions read naturally by screen reader; technical details panel is a native `<details>` element so AT users get standard disclosure semantics
- All form errors are announced via `aria-live="polite"` on the callout container
- **Contrast on the gradient summary card (5.2)** — all white text uses `rgba(255,255,255,0.92)` minimum, verified ≥4.5:1 against the darkest point of the indigo→slate gradient. The two largest type elements (repo name title, stats numbers) use full `#ffffff` and are well clear of AA
- **External links** (Scorecard "Learn more" on 2.2) use `target="_blank" rel="noopener noreferrer"` and include the `open_in_new` icon as a visible cue that the link leaves the app

## Design system compliance

Confirmed across every frame in the gallery:

- No `1px solid` borders — tonal layering only, ghost borders at 15% opacity where a divider is unavoidable
- Text is `on-surface` (`#2b3437`) — never `#000`
- Sentence case on every label, heading, and button (no Title Case, no ALL CAPS except severity chip text which is `uppercase tracking-wider` — existing convention)
- Severity uses `error` / `tertiary` / `on-surface-variant` tokens; success uses `tertiary`, never arbitrary `green-*`
- Manrope for headlines (600–800), Inter for body (400–600)
- Only Material Symbols Outlined icons
- Primary `#4d44e3` is used for focus, CTAs, grade ring fill, and the shield body — consistent across every surface

### Sanctioned exceptions

- **Gradient surface on the shareable summary card (5.2).** The 1200×630 export artifact uses a `linear-gradient(135deg, #4d44e3 0%, #575e78 100%)` background. This is the first surface in the product to combine primary + tertiary as a gradient, and it is an **approved exception scoped to generated share artifacts only** (Revision 4, 2026-04-15). Rationale: the summary card lives outside the app — on Twitter, in a README, on a slide — and needs a distinct, recognizable visual identity that reads as "Cliff" at thumbnail size. This exception does **not** extend to app chrome or any in-app surface. App surfaces continue to use tonal layering (Level 0 / 1 / 2) with no gradients. If a future design proposes a gradient in app chrome, it requires a new sanctioned-exception entry or a design system amendment.
- **White text on the gradient surface uses `rgba(255,255,255,0.92)` to `rgba(255,255,255,0.98)`** for small eyebrow/footer text, verified to meet WCAG AA (≥4.5:1) against the full gradient range. The previous `opacity-70` / `opacity-80` values from Revision 3 are corrected in Revision 4.

## Open questions for CEO

None blocking. Two optional calls if you have strong preferences:

1. **Welcome screen secondary CTA copy** — "I already have findings" (today) vs. "Skip setup" (more literal). UX leans to the former: it names the person's state, not the wizard's.
2. **Summary card image format** — PNG only (simpler) vs. PNG + SVG (more flexible, slightly more engineering). UX leans PNG-only for v1.1; SVG can come later if users ask.

## Change log

**2026-04-15 · Revision 4 · design critique applied**

*All three priority items from the `/design-critique` pass have been resolved. Minor flags addressed as well.*

- **5.1 Celebration · action hierarchy rebalanced.** Three co-equal buttons replaced with one primary ("Download summary image", filled primary, `py-3.5 px-8`, slightly larger than standard to own the moment) + two subordinate text-link actions below ("Copy text summary" and "Copy markdown", separated by a 1px ghost divider). The full side-by-side action panel still lives on 5.2 directly below the celebration. Body copy updated: "The full summary panel with previews is just below" — points the user at 5.2.
- **5.2 Tile pattern unified.** Download tile now includes a metadata preview row (`image` icon + filename "fast-markdown_cliff-summary_2026-04-14.png" + "1200×630 · ~80 KB") matching the `<pre>` preview blocks on the Copy tiles. All three tiles now follow the same shape: header (icon + title + one-line description) → preview block (file metadata or code snippet) → action button.
- **5.2 Summary card contrast bumped to AA.** Text on the indigo→slate gradient was previously using Tailwind `opacity-70`/`opacity-80` (approximately 4.1:1, borderline). Replaced with explicit `rgba(255,255,255,0.92)` for eyebrow/footer/labels and `rgba(255,255,255,0.95–0.98)` for the completed date and Grade label. Divider line strengthened from `bg-white/20` to `bg-white/30`. Stats row breathing room increased from `mb-5` to `mb-7` and label margin from `mt-1` to `mt-1.5`.
- **6.1 Aside streamlined.** The "Re-open summary card" text link is removed. The shield SVG is now the affordance: wrapped in a `<button type="button" aria-label="Re-open shareable summary card">` with a `focus-visible:ring-2 ring-primary/40` state and a `hover:scale-105` transition. A "Tap for summary" micro-label fades in on hover (opacity-0 → 100) so the affordance is discoverable without cluttering the default state. The aside now has exactly one primary CTA (Re-assess now) and one secondary link (View assessment history).
- **Gallery hero · revision note moved to a collapsed `<details>` block** labeled "Changelog · Revision 4 (2026-04-15)" with a chevron icon that rotates on open. The hero now leads with product description, not document history. Both Rev 3 and Rev 4 notes are preserved inside the block.
- **Scorecard external link · `rel="noopener noreferrer"`** added alongside `target="_blank"` to meet standard external-link security hygiene. Flagged in the spec for `/app-builder` to preserve in the real implementation.
- **Design system compliance · sanctioned exception documented.** The 5.2 gradient surface is now an explicit approved exception (scoped to generated share artifacts only). Added a "Sanctioned exceptions" subsection to the Design system compliance section that names the gradient, the rationale, and the scope boundary. App chrome still uses pure tonal layering.

Design system rules still pass end-to-end: no `1px solid` borders, tonal layering preserved, sentence case maintained, `on-surface` for text, severity tokens consistent. Gradient exception is the only new deviation and is explicitly bounded.

**2026-04-15 · Revision 3 · PRD scope change — public badge deferred to v1.2**

- **Title** — "Earn the badge" renamed to "From zero to secure" to match the revised PRD-0002
- **Section 5** — renamed "Earning the badge" → "Completion ceremony"
- **2.2 Report card** — "Badge preview" card relabeled "Completion progress". Subtitle now mentions the shareable summary rather than a README badge. Added a new static info-line at the bottom of the report card pointing to OpenSSF Scorecard as an independent third-party standard (external link only — no API call, no "no score available" state)
- **2.2 Report card** — grade hero copy updated from "Fix 2 more items to earn the badge" to "Fix 2 more items to reach security completion"
- **4.1 Posture** — "Needed for badge" pill relabeled "Needed for completion"
- **5.1 Celebration** — headline changed from "Badge earned" to "Security complete". Body copy no longer promises README placement. Shield SVG caption changed from "LAST VERIFIED" to "COMPLETED". The two-CTA row (Add to README / Share) is replaced with three share actions: Download image, Copy text summary, Copy markdown. Small reassurance line added: "Cliff never writes to your README"
- **5.2 · full replacement** — "Add badge to README" dialog removed. Replaced with a full-width "Shareable summary · three actions" panel that lives on the same page below the celebration. Shows a 1200×630 rendered preview of the summary card (repo name, date, vulns fixed, posture checks, PRs merged, grade) beside three action tiles (download PNG, copy text, copy markdown). A footer line makes the trust posture explicit: "No Cliff-hosted URL, no tracking, no account required. v1.2 will add an optional public badge with verification — not today."
- **6.1 Dashboard · returning** — "Active badge" label renamed "Security complete". "Last verified" renamed "Last assessed". The "Fresh · valid for 76 more days" freshness band is removed entirely (nothing public to go stale). Added a "Re-open summary card" link below the aside. Body copy no longer references a "fresh badge"
- **6.1 Activity list** — "Badge earned for the first time" → "Completion reached · summary generated"
- **6.2 Banner** — reframed from "Your badge is still valid" to "You're still at completion — for now". Body copy removed the promise to "refresh the 'last verified' date on your README" (since Cliff never wrote to the README). Instead: "Your existing summary card is still valid until you regenerate it"
- **Component inventory** — `AddBadgeDialog` and `FreshnessCard` removed. `BadgePreviewCard` renamed to `CompletionProgressCard`. `BadgeEarnedCelebration` renamed to `CompletionCelebration`. Added `ShareableSummaryCard`, `SummaryActionPanel`, `CompletionStatusCard`, `ScorecardInfoLine`

Design system compliance re-verified end-to-end: no `1px solid` borders, tonal layering preserved, sentence case maintained, `on-surface` for text, severity tokens consistent. The shield SVG itself is unchanged — it remains the visual emblem of completion, just no longer bound to a README-writing workflow.

**2026-04-14 · Revision 2 · design critique applied**

- **1.0 Welcome** — removed the "I already have findings" secondary CTA. Single "Get started" primary.
- **1.1 Connect project** — collapsed the two-step "Test connection → Continue" flow to a single "Verify and continue" primary. Validation runs inline; on success the verified card shows briefly then auto-advances.
- **1.1** — removed redundant `repo` scope explanation under the PAT input; help link on the label now leads to the dialog (1.1a) which owns the full walkthrough.
- **1.1a · new** — "How to create a token" modal with dimmed, slightly blurred backdrop, 5-step walkthrough, vault reassurance footer, deep-link to `github.com/settings/tokens`.
- **1.3 Verified** — replaced redundant "Continue to AI setup" button with a small spinner + "Loading Step 2" inline hint, reinforcing that Step 1 auto-advances. "Change" action wrapped in a padded button for touch target.
- **2.2 Report card** — demoted "Import findings" from header-level secondary button to a subtle text link inside the vulnerabilities card ("Already using Snyk, Trivy, or Dependabot?"). Primary "Start fixing" is now uncontested.
- **2.2 Posture summary** — failing items now use `primary-container/25` background with primary-colored error icon (not filled-red `cancel`). Matches calm-authority tone.
- **3.1 Findings queue** — reweighted "Solve" buttons: filled primary on the top-severity (critical) row only; all other rows use a tonal `surface-container-low` button with primary text. Headline plain-language sentences now have uncontested visual dominance.
- **3.2 Finding detail** — three equal-weight actions collapsed to primary / text / icon-menu: "Solve this finding" (filled), "Defer" (text), overflow menu (`more_horiz`) absorbs "Mark not applicable" and future secondary actions.
- **4.1 Posture tab** — "Blocks badge" error chip replaced with softer "Needed for badge" chip in `primary-container/60`. Failing-item container shifted from `error-container/15` to `primary-container/25`. Icon is the unfilled `error` in primary color — still signals attention, no longer signals alarm.
- **5.1 Badge earned** — reworked hierarchy: eyebrow now reads "Grade A · 5 of 5 criteria met", headline is "Badge earned", verification date moved into the body sentence. Shield SVG is the uncontested hero. Container wrapped with `role="status" aria-live="assertive"` so the celebration is announced to screen readers once on mount.
- **5.2 Add to README dialog** — removed stray `<em>` HTML tag from the markdown preview; the preview block now contains pure markdown the user can copy verbatim.
- **6.1 Dashboard · returning** — merged the floating `A` grade into the freshness aside. Aside now shows: active badge shield → Secured by Cliff → `A · 5 of 5` + "Last verified · 14 days ago" side-by-side (separated by a ghost divider) → freshness band → re-assess CTA. Main column focuses on "what's changed" content only.
- **6.2 Re-assess** — banner reframed from red-alert to calm-authority. New banner uses `surface-container-lowest` with a vertical tertiary accent bar, shield icon, and reassurance-first copy: "Your badge is still valid". The error signal now comes from the finding card itself (which is appropriately red-keyed), not from a whole-page alarm.

Gallery file regenerated. Design system rules still pass end-to-end: no `1px solid` borders, tonal layering preserved, sentence case maintained, `on-surface` for text, severity tokens consistent.

**2026-04-14 · Revision 1**

- Initial draft covering all 6 user stories and 14 frames.

---

## Handoff

Once approved, `/architect` takes this spec plus `PRD-0002-earn-the-badge.md` into an implementation plan (`IMPL-0002-earn-the-badge.md`), then R&D splits between `/app-builder` (onboarding wizard, dashboard page, findings detail, posture interactions, dialogs, shield SVG) and `/cliff-agent-orchestrator` (SECURITY.md + Dependabot single-shot agents, plain-language prompt extension to the LLM normalizer).
