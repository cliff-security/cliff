# Handoff: PRD-0003 — Security assessment v2 (design pass)

## Overview

Design pass for **PRD-0003 (Security assessment v2)**, Cliff's v0.2 release. This package covers six product surfaces that ship the move from homebrew scanning → industry-standard scanners (Trivy 0.52, Semgrep 1.70), expand posture from 7 → 15 checks across four categories, and recalibrate the letter grade from 5 → 10 criteria.

The mental model for Alex (the OSS maintainer) does not change — connect a repo, get a report card, fix things, reach completion. The report card just gets deeper and more credible.

## About the design files

The files in this bundle are **design references created in HTML** — prototypes that show the intended look, layout, and behavior. They are **not production code to copy directly**.

The implementation task is to **recreate these designs in Cliff's existing frontend codebase** (React + Tailwind, per `frontend/src/`) using its established patterns, tokens, and component library — including the four-state posture-row pattern that PRD-0004 owns. If you find a conflict between this handoff and a PRD-0004 component decision, **PRD-0004 wins** for shared chrome.

## Fidelity

**High fidelity.** Pixel-perfect mockups using the production Serene Sentinel design system tokens (see `colors_and_type.css`). Recreate them pixel-perfectly in the target codebase using its existing libraries, the design system tokens already shipped, and the React patterns under `frontend/src/components/`.

## Surfaces in this pass

The design canvas (`PRD-0003 design.html`) contains six surfaces. Two have alternative variations.

| # | Surface | Variations | Component file |
|---|---------|-----------|----------------|
| 1 | Report card — posture redesigned | A: stacked groups (single tall card) · B: 2×2 grid of category cards | `surfaces/report-card.jsx` |
| 2 | Assessment in progress (scanner stages) | — | `surfaces/assessment-progress.jsx` |
| 3 | Assessment-complete summary (interstitial) | A: three side-by-side cards · B: editorial — grade as the hero | `surfaces/assessment-complete.jsx` |
| 4 | Onboarding step 3 (start assessment) | — | `surfaces/onboarding-step3.jsx` |
| 5 | Completion progress (10 criteria) | — | `surfaces/completion-progress.jsx` |
| 6 | Shareable summary card (1200×630) | — | `surfaces/share-card.jsx` |

**Recommended variation picks** (mine, not binding — Gal to decide):
- Surface 1: **A** (single tall card with stacked groups). Calmer scan path, matches the "editorial gallery" tone better than the grid.
- Surface 3: **A** (three-card summary). Bridges to the report card more cleanly. B is more dramatic but invents a different visual rhythm than what Alex sees on the next screen.

---

## Hard rules (non-negotiable, inherited from Serene Sentinel)

1. **No-Line Rule.** No `1px solid` borders. Use tonal layering (`surface` → `surface-container-low` → `surface-container-lowest`), spacing, or shadows.
2. **Sentence case everywhere.** Labels, headers, buttons. The only exception: 10px uppercase status labels (eyebrows + the PRD-0004 posture-row leading column).
3. **No pure black.** Body text is `#2b3437` (token: `on-surface`).
4. **Severity colors are tokens.** `text-tertiary` / `bg-tertiary-container/30` for success/medium, `text-error` / `bg-error-container/30` for critical/high. Never raw greens or reds.
5. **Reduced motion.** Every animation respects `@media (prefers-reduced-motion: reduce)`.
6. **Color is never the only signal.** Severity / status / state always carry an icon shape AND a text label in addition to color.

---

## Design tokens

Full set lives in `colors_and_type.css`. The values used in this design pass:

### Color (Material Tonal palette)

| Role | Token | Hex |
|------|-------|-----|
| Primary brand | `primary` | `#4d44e3` |
| Primary dim (hover) | `primary-dim` | `#4034d7` |
| Primary container | `primary-container` | `#e2dfff` |
| Primary container dim | `primary-fixed-dim` | `#d2d0ff` |
| On-primary text | `on-primary` | `#faf6ff` |
| On-primary container | `on-primary-container` | `#3f33d6` |
| Tertiary (success) | `tertiary` | `#575e78` |
| Tertiary container | `tertiary-container` | `#d2d9f8` |
| On-tertiary container | `on-tertiary-container` | `#444c65` |
| Error (critical/high) | `error` | `#9e3f4e` |
| Error container | `error-container` | `#ff8b9a` |
| On-error container | `on-error-container` | `#782232` |
| Surface (L0 page) | `surface` / `background` | `#f8f9fa` |
| Surface container low (L1) | `surface-container-low` | `#f1f4f6` |
| Surface container lowest (L2 cards) | `surface-container-lowest` | `#ffffff` |
| Surface container (chips) | `surface-container` | `#eaeff1` |
| Surface container high | `surface-container-high` | `#e3e9ec` |
| On-surface text | `on-surface` | `#2b3437` |
| On-surface variant (muted) | `on-surface-variant` | `#586064` |
| Outline variant | `outline-variant` | `#abb3b7` |

### Typography

| Use | Family | Weight | Size |
|-----|--------|--------|------|
| Page title | Manrope | 800 | 32px / 1.1 / -0.02em |
| Section headline | Manrope | 700 | 22–28px |
| Card heading | Manrope | 700 | 17px |
| Eyebrow / category label | Inter | 700 | 11px / `uppercase tracking-wider` / `text-on-surface-variant` |
| Body | Inter | 400 | 14px / 1.55 |
| Small body / detail | Inter | 400 | 13px |
| Label / chip | Inter | 500–600 | 11–12px |
| Numerals | tabular-nums | — | — |
| Code / IDs | JetBrains Mono | 400 | 13px |

### Radii

`xs:4px · sm:8px · md:12px · lg:16px · xl:20px · pill:9999px`. Rounded-3xl (24px) is used on the larger content cards.

### Spacing rhythm

Page padding: `px-8 py-7`. Card gap in lists: `gap-2` (rows) / `gap-3` (subgroups). Section gap: `gap-5` to `gap-7`. Sidebar nav rail: fixed `w-20`.

### Shadows

```
--shadow-sm: 0 1px 3px rgba(43,52,55,.05), 0 1px 2px rgba(43,52,55,.03);
--shadow-md: 0 4px 12px rgba(43,52,55,.06), 0 1px 3px rgba(43,52,55,.04);
```

### Iconography

Google Material Symbols Outlined only.

| Use | Icon | Variation |
|-----|------|-----------|
| Pass | `check_circle` | filled, `text-tertiary`, 18px |
| Fail / critical | `cancel` | filled, `text-error`, 18px |
| Advisory / info | `info` | outline, `text-on-surface-variant`, 18px |
| Pending / to do | `radio_button_unchecked` | outline |
| Running | 28px circular spinner (CSS border) | — |
| Verified / scanned-by | `verified` | outline |
| Trivy | `bug_report` | outline |
| Semgrep | `code` | outline |
| Posture checks | `rule` | outline |
| Re-assess | `refresh` | outline |
| Generator agent CTA | `auto_fix_high` | outline |

---

## Surface specifications

### Surface 1 — Report card with grouped posture (the home base)

**Purpose.** Where Alex spends most of their time. Replaces the flat list of 7 posture checks with 4 grouped categories totaling 15 checks.

**Layout** (variation A, recommended):
- Page padding `px-8 py-7`. Page title eyebrow ("Repository") + H1 (`galanko / cliff-demo`) at top.
- Stacked sections, gap `20px`:
  1. **Hero card** (`bg-surface-container-lowest`, `rounded-3xl`, `p-7`):
     - Three-column flex: GradeRing (120px) · narrative (eyebrow + `Nearly there.` headline + supporting line) · last-assessed metadata + `Re-assess` ghost pill button.
     - Below: a horizontal divider (subtle inset shadow, not a border) and a row with `Scanned by` eyebrow on the left + `ToolPillBar` on the right. Tools shown in `done` state with result counts.
  2. **Completion progress card** (`bg-surface-container-lowest`, `rounded-3xl`, `p-6`): see Surface 5.
  3. **Two-column row** (`grid-cols-[380px_1fr] gap-5`):
     - Left: Vulnerabilities card (4 severity tiles + Semgrep callout + "Start fixing" primary CTA).
     - Right: Posture card with stacked groups.
- **Posture card structure** (`bg-surface-container-lowest`, `rounded-3xl`, `p-6`, gap `24px`):
  - Header: card title `Repo posture` + `12 of 15 checks pass · 3 advisory`.
  - Four group blocks in fixed order: **CI supply chain · Collaborator hygiene · Code integrity · Repo configuration**.
  - Each group: `CategoryHeader` (eyebrow + "X of Y" + 80px progress rail) followed by an unordered list of rows.

**Posture row variants** (the four-state pattern is owned by PRD-0004; PRD-0003 fills it with content):

| State | Treatment |
|-------|-----------|
| Pass | Inline row, `check_circle` filled in `text-tertiary`, label in `text-on-surface`. |
| Done (agent finished) | Same as Pass + a right-aligned `Draft PR ↗` link in `text-primary`. |
| Fail | Card-style row, `bg-primary-container/30` `rounded-2xl` `p-4`. Filled `cancel` icon in `text-error`. Title (semibold) + body (`text-on-surface-variant`, 13px). When fixable: a primary pill button beneath the body, indented to the title. |
| Advisory | Inline row, outline `info` icon, label in `text-on-surface-variant`, right-aligned `advisory` chip in `bg-surface-container-high`. |

**Mock data used (consistent across all surfaces):**
- Grade B · 8/10 criteria · 12/15 posture pass · 3 advisory.
- Vulns: 0 critical, 2 high, 5 medium, 3 low (10 total). 3 are Semgrep findings.
- Failing posture checks: "Actions not pinned to SHA" (CI) and "Code owners file missing" (Code integrity). Both have generator CTAs.

**Variation B** (`PostureCardGrid`): Same content but rendered as four equal cards in a 2-column grid. Use when horizontal screen real estate is wide enough; otherwise A is the default.

### Surface 2 — Assessment in progress

**Purpose.** Builds trust by naming the real tools. Replaces the previous opaque "Running checks…" with named, time-estimated steps.

**Layout:**
- Page header (eyebrow + repo H1) — same as report card.
- **Live assessment card** (`bg-surface-container-lowest`, `rounded-3xl`, `p-8`, mb-5):
  - Top row: 56×56 rounded-2xl `bg-primary-container` containing a 28px circular spinner · headline (`Assessing your repository` + supporting copy) · right-aligned elapsed time (mono, `01:24`).
  - Tool pill bar row: `Powered by` eyebrow + `ToolPillBar` (Trivy=`active` w/ pulse, Semgrep=`pending`, posture=`pending`).
  - Step list (gap `6px`):
    - Done: `check_circle` filled tertiary + label + right-aligned chip with result (e.g., `npm + Python`).
    - Running: card-style row (`bg-primary-container/30`, `rounded-2xl`, `p-4`) with spinner + label + right-aligned percent + thin progress bar + one-line detail string indented to the label.
    - Pending: outline `radio_button_unchecked` icon at 70% opacity + muted label.
- **Previous assessment card** (`bg-surface-container-low`, `opacity-80`): keeps user oriented while scan runs. History icon + `Previous assessment` eyebrow + `Grade B · 8 of 10 criteria · 3 days ago` + right-aligned `View report` link.

**Step keys (v0.2):** `detect` · `trivy_vuln` · `trivy_secret` · `semgrep` · `posture` · `descriptions`.

### Surface 3 — Assessment-complete summary (interstitial)

**Purpose.** Bridges the gap between "scan running" and "report card with 15 checks in 4 categories" so it doesn't land as a surprise.

**Layout (variation A, recommended):**
- Centered column, max-width `768px`, `py-10`.
- Top hero: 64px tertiary-container circle with filled `check` icon · `Assessment complete` eyebrow · `Here's what we found.` H1 · supporting copy · `ToolPillBar` (all done).
- **Three side-by-side cards** (`grid-cols-3 gap-3`):
  1. **Vulnerabilities** card (L2 surface): big number `10` + `findings total` + severity chips row + small "Trivy · Semgrep" footer.
  2. **Posture** card (L2 surface): big number `12/15` + `checks pass` + bulleted list of 4 category names.
  3. **Quick wins** card (`bg-primary-container/40`, accent): big number `3` + `we can fix automatically` + 3 short labels.
- **Grade preview row** (`bg-surface-container-low`, `rounded-3xl`, `p-6`): mini GradeRing (72px) + `Your grade` eyebrow + `8 of 10 criteria met — Grade B` + supporting line.
- **Single CTA**: centered `View your report card →` primary pill, `px-6 py-3 rounded-full bg-primary text-on-primary`.

**Show only when:** First assessment after onboarding, or after a re-assessment when the posture check count changed. Skip on subsequent visits — load report card directly.

**Variation B**: editorial vertical with a 64px Grade letter as the hero next to a 140px GradeRing. More dramatic; recommended only if user testing shows people skip past A's three cards.

### Surface 4 — Onboarding step 3

**Purpose.** Sets expectations on minute one. Builds trust by naming the tools.

**Layout:**
- Centered, max-width `672px`, `py-12`.
- 3-step indicator at top (1 Connect repo · 2 Configure AI · 3 Start assessment, where 1+2 are done, 3 is active).
- Card (`bg-surface-container-lowest`, `rounded-3xl`, `p-9`):
  - `Step 3 of 3` eyebrow + H1 `Start security assessment`.
  - Body paragraph with the exact copy: *"We'll scan your repository using industry-standard security tools and run 15 posture checks on your repo's security configuration. This usually takes 2–5 minutes."*
  - **Powered-by row** (`bg-surface-container-low`, `rounded-2xl`, `p-4`): eyebrow + `ToolPillBar` (all pending).
  - **Step previews** (4 items, was 3 in v1.1) with explicit time estimates: 10s · 60s · 30s · 60s. Each is a `bg-surface-container-low` rounded-2xl row with numbered circle + title + time + body.
  - Footer row: `← Back` link on the left + primary `Start assessment` CTA with `play_arrow` icon on the right.

### Surface 5 — Completion progress (10 criteria)

**Purpose.** Visual recalibration: the 5-slot pill meter from PRD-0002 doesn't scale to 10. Switch to a continuous progress bar with tick marks.

**Layout:**
- Card (`bg-surface-container-lowest`, `rounded-3xl`, `p-8`, max-w `672px`).
- Header: `Completion progress` eyebrow + `8 of 10 criteria met` H2 on the left, big `80%` numeral on the right.
- **Progress bar:** 12px tall, `rounded-full bg-surface-container-high`, filled portion `bg-primary` to 80%. Overlay 11 vertical 1.5px ticks (positions 0..10) in `bg-surface-container-lowest/70`.
- Tick labels `0..10` row beneath the bar in tabular-nums.
- **Criteria chip grid:** `grid-cols-1 md:grid-cols-2 gap-2`. Met chips: `bg-tertiary-container/45` + filled `check_circle` + label in `text-on-tertiary-container`. Unmet chips: `bg-surface-container-high` + outline `radio_button_unchecked` + muted label. All chips are pill-shaped (`rounded-full px-3 py-2`).
- Footer line, centered: *"Reach 10 of 10 to unlock Grade A and the shareable summary."*

**The 10 criteria, in order:** SECURITY.md · Dependabot · No criticals · No highs · Branch protection · No secrets · CI SHA-pinned · No stale collaborators · Code owners · Secret scanning.

### Surface 6 — Shareable summary card

**Purpose.** 1200×630 social-share PNG generated when Alex hits Grade A.

**Spec:**
- Canvas: 1200×630, indigo gradient (`#2a13c5 → #4034d7 → #4d44e3`), 135deg.
- Decorative concentric circles, top-right, 15% opacity, white stroke.
- Header row: 44px rounded-2xl mark + `Cliff` wordmark · right-aligned `SECURED` eyebrow at 70% opacity.
- Hero: 192px white-bordered grade ring with `A` glyph (Manrope 800, 112px) + sub-eyebrow `GRADE`. To the right: repo eyebrow + `10 criteria met.` H1 (Manrope 800, 68px) + supporting `Vulnerabilities resolved. Posture hardened. CI pinned.`
- Footer: scanned-by line `Scanned by: Trivy 0.52 · Semgrep 1.70 · 15 posture checks` (white at 60%, Inter 500, 14px) + the URL `cliff.dev / galanko / cliff-demo` · right-aligned date.

**Delta from PRD-0002:** Replace `5 criteria met` → `10 criteria met`. Add the `Scanned by:` line above the wordmark. Otherwise visually identical.

---

## Shared components — what to extract

Implement these once and reuse:

| Component | Props | Where used |
|-----------|-------|-----------|
| `SideNav` | `active` | All in-app surfaces |
| `ToolPillBar` | `tools: { label, icon, state, result? }[]`, `size?: 'sm' \| 'md'` | 1, 2, 3, 4 |
| `GradeRing` | `grade`, `percent`, `size?`, `sub?` | 1, 3, 6 |
| `PillButton` | `icon?`, `variant?`, `size?` | 1, 2, 3, 4 |
| `SeverityChip` | `kind`, `count` | 3 |
| `PostureRow*` (Pass / Fail / Advisory / Done) | varies | 1 |
| `CategoryHeader` | `title`, `done`, `total` | 1 |

`ToolPillBar` state colors:
- `pending` → `bg-surface-container-high text-on-surface-variant`
- `active` → `bg-primary-container text-on-primary-container animate-pulse-subtle`
- `done` → `bg-tertiary-container/60 text-on-tertiary-container` + filled `check_circle` icon
- `skipped` → `bg-surface-container-high text-on-surface-variant/70 line-through`

---

## Interactions & behavior

- **Re-assess button** → triggers Surface 2; the report card stays visible beneath as a "Previous assessment" card. Owned by PRD-0004 Story 1; PRD-0003 only contributes the new scanner stages.
- **Generator CTA on a Failing posture row** → row immediately flips to "Running" state (optimistic) and the button is replaced by a non-interactive chip "Agent is drafting a PR…" (per PRD-0004 Story 3). On success, row → Done state with `Draft PR ↗` link.
- **Progress bar** in Surface 2 should animate smoothly between values (CSS transition `width 600ms ease-out`), not jump.
- **Tool pill — active** uses a 2.4s subtle pulse (opacity 1 → 0.65 → 1), CSS-only.
- **`role="status" aria-live="polite"`** on Surfaces 2 and 3. Surface 6 (completion ceremony) uses `aria-live="assertive"` once.
- **Reduced motion**: every keyframed animation must be disabled under `@media (prefers-reduced-motion: reduce)`.

## State management

Most of this is driven by the existing assessment engine. Frontend-side:
- `assessment.status`: `idle | running | complete` → routes to report card / progress / interstitial.
- `assessment.steps[]`: per-step `{ key, label, state, percent?, detail?, result? }`.
- `assessment.tools[]`: per-tool `{ id, label, version, state }`.
- `posture.checks[]`: per-check `{ id, category, state, severity?, body?, fixable?, prHref? }`.
- `criteria[]`: 10 items, each `{ id, label, met }`.

Persist `firstAssessmentSeen` (boolean) to decide whether Surface 3 shows or is skipped.

## Accessibility

- WCAG 2.1 AA. Visible focus rings (`ring-2 ring-primary/60 ring-offset-2`) on every interactive element.
- Touch targets ≥ 44×44px.
- All Material Symbols that aren't decorative get `aria-label`; decorative icons get `aria-hidden="true"`.
- Color contrast ≥ 4.5:1 for body, ≥ 3:1 for large text.
- Test posture rows in deuteranopia + protanopia simulation — icon shape + text label must convey state without color.

## Files in this bundle

```
PRD-0003 design.html              — root, design canvas
design-canvas.jsx                 — pan/zoom canvas runtime (do not port)
surfaces/shared.jsx               — SideNav, ToolPillBar, GradeRing, PillButton, SeverityChip, BrowserChrome
surfaces/report-card.jsx          — Surface 1 (variations A & B)
surfaces/assessment-progress.jsx  — Surface 2
surfaces/assessment-complete.jsx  — Surface 3 (variations A & B)
surfaces/onboarding-step3.jsx     — Surface 4
surfaces/completion-progress.jsx  — Surface 5
surfaces/share-card.jsx           — Surface 6
surfaces/app.jsx                  — composition / canvas wiring
colors_and_type.css               — production design tokens (this is the source of truth)
uploads/PRD-0003-claude-design-brief.md   — the design brief these mockups answer
uploads/PRD-0003-security-assessment-v2.md — the full PRD
```

## Out of scope for this implementation

- The four-state posture-row pattern itself (PRD-0004 Story 3).
- The "Run assessment" button on Dashboard, the dashboard nav entry, the post-onboarding redirect (PRD-0004 Story 1, 2).
- The side nav, workspace layout, and chat surface — already stable.
- A `warning` severity token family for medium-severity findings — reserved by PRD-0004; placeholder neutral chip used until it lands.

## Open questions for the architect

1. Should Surface 3 (assessment-complete interstitial) be a standalone route or a modal overlay on the report card route?
2. Where does the `firstAssessmentSeen` flag live — local storage, user record, or assessment record?
3. Should the per-category progress rail (Surface 1) animate when a fail flips to pass mid-session?
