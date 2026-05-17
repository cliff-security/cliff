# Design brief — PRD-0003 (Security assessment v2)

> Self-contained brief for handing off to Claude design (or any design tool that doesn't have access to the Cliff codebase). The full PRD lives at `docs/product/prds/PRD-0003-security-assessment-v2.md`; reference HTML mockups live at `frontend/mockups/html/prd-0003-*.html`. This document compresses everything a designer needs into one place.

**Author:** Gal Ankonina (CEO, Cliff)
**Last updated:** 2026-04-25
**Sequencing:** Ships as v0.2, after PRD-0004 (v0.1 alpha blockers)

---

## 1. What we're building

Cliff is a self-hosted cybersecurity remediation copilot for open-source maintainers. It scans a repo, surfaces security findings, and walks the maintainer through fixing them — all from a chat-led web workspace. Single-user community edition, AGPL-3.0, runs as one Docker container.

**This release (v0.2)** swaps Cliff's homebrew vulnerability scanning for industry-standard tools (Trivy + Semgrep), expands posture checks from 7 to 15 across four categories (CI supply chain, collaborator hygiene, code integrity, repo configuration), and recalibrates the letter grade from 5 to 10 criteria. Alex's mental model doesn't change — connect a repo, get a report card, fix things, reach completion. The report card just gets deeper and more credible.

## 2. Who you're designing for

**Alex, the open-source maintainer.** Not a security expert. Has shipped 5+ years of code, runs one or two side projects on GitHub, has heard of CVEs but doesn't understand CVSS scoring. Wants to do the right thing for their users without becoming a security professional. Will use Cliff on their own repo, alone, in a single browser tab.

**Emotional truth:** Alex is a little embarrassed they don't already have this stuff dialed in. The product must reduce that anxiety, not amplify it. Tone is calm, authoritative, gallery-like — never alarmist, never condescending, never rewarding panic.

## 3. What you're producing

Six surfaces, listed by priority. Each maps to one or more user stories in PRD-0003.

| # | Surface | Why it matters | Stories |
|---|---------|---------------|---------|
| 1 | **Report card — posture section, redesigned** | The report card is the product's home. Posture goes from a flat list of 7 to a categorized list of 15 across four groups. This is where most of Alex's time will be spent | Stories 2, 3, 4, 6 |
| 2 | **Assessment progress with scanner-specific stages** | Builds trust by naming the real tools (Trivy 0.52, Semgrep 1.70). Replaces the previous opaque "Running checks…" with named, time-estimated steps | Stories 1, 5 |
| 3 | **Assessment-complete summary (new interstitial)** | Bridges the gap between "scan running" and "report card with 15 checks in 4 categories" — without it, the report card lands as a surprise | Stories 1, 6 |
| 4 | **Onboarding step 3 — copy + tool name-drops** | Sets expectations on minute one. Step changes from 3 to 4 stages with time estimates | Story 5 |
| 5 | **Completion progress card — 10 criteria** | Visual recalibration: pill meter (5 slots) → continuous progress bar with 10 tick marks | Story 6 |
| 6 | **Shareable summary card — text refresh** | Minor: "5 criteria met" → "10 criteria met"; add "Scanned by: Trivy 0.52 · Semgrep 1.70" line | Story 6 |

> **What you do NOT design here.** PRD-0004 (v0.1 alpha) already owns: the "Run assessment" button on Dashboard, the dashboard nav entry, the post-onboarding redirect, the four-state posture-row pattern (To do / Running / Done / Failed with leading icon column + row tint + action slot variants). Inherit those patterns; do not redesign them.

---

## 4. Design system — "The Serene Sentinel"

The product follows a single design system. Every surface you produce must obey these rules.

### 4.1 Hard rules (non-negotiable)

1. **No-Line Rule.** Never use `1px solid` borders. Express depth and separation via tonal layering, spacing, or shadows. The only exception is the "ghost border" at 15% opacity (used sparingly for emphasis where tonal shift isn't enough).
2. **Sentence case everywhere.** Labels, headers, buttons. No Title Case. No ALL CAPS (one exception: 10px uppercase status labels in the posture-row leading column from PRD-0004).
3. **No pure black.** Body text is `#2b3437` (token: `on-surface`). Never `#000000`.
4. **Tonal layering for depth.** Three levels: Level 0 `#f8f9fa` (page background, `surface`), Level 1 `#f1f4f6` (`surface-container-low`), Level 2 `#ffffff` (`surface-container-lowest`). Cards usually sit at L2 against an L1 page.
5. **Severity colors are tokens, never raw greens/reds.** Use `text-tertiary` / `bg-tertiary-container/30` for success or medium, `text-error` / `bg-error-container/30` for critical/high, `text-on-surface-variant` for low. Never `green-500`, never `red-600`.
6. **Reduced motion.** Every animation respects `@media (prefers-reduced-motion: reduce)`.

### 4.2 Color tokens (full palette)

The product is light-mode by default. Indigo primary, muted desaturated accents.

| Role | Token | Hex |
|------|-------|-----|
| Primary brand | `primary` | `#4d44e3` |
| Primary container | `primary-container` | `#e2dfff` |
| On-primary text | `on-primary` | `#faf6ff` |
| Tertiary (success/positive) | `tertiary` | `#575e78` |
| Tertiary container | `tertiary-container` | `#d2d9f8` |
| Error (critical/high) | `error` | `#9e3f4e` |
| Error container | `error-container` | `#ff8b9a` |
| Background / surface (L0) | `surface` | `#f8f9fa` |
| Surface L1 | `surface-container-low` | `#f1f4f6` |
| Surface L2 | `surface-container-lowest` | `#ffffff` |
| Surface container (chip bg) | `surface-container` | `#eaeff1` |
| Surface container high | `surface-container-high` | `#e3e9ec` |
| On-surface text | `on-surface` | `#2b3437` |
| On-surface-variant (muted) | `on-surface-variant` | `#586064` |
| Outline-variant | `outline-variant` | `#abb3b7` |

**Coming via PRD-0004 (use a placeholder neutral chip until it lands):** a `warning` token family (`warning`, `warning-container`, `on-warning-container`, `warning-dim`) for medium-severity findings — currently mis-rendered as green/tertiary. The architect picks the hex values in a small ADR alongside PRD-0004.

### 4.3 Typography

| Use | Family | Weights |
|-----|--------|---------|
| Headlines (page titles, card headings, big numbers) | **Manrope** | 600 / 700 / 800 |
| Body, labels, controls | **Inter** | 400 / 500 / 600 |
| Code, inline tech strings | System mono | 400 |

Common type pairings:
- Page title: Manrope 700, ~32px, `text-on-surface`
- Section heading: Manrope 600, ~20px
- Card heading: Manrope 600, ~16px
- Eyebrow / category label: Inter 700, 12px, `uppercase tracking-wide`, `text-on-surface-variant`
- Body: Inter 400, 14px, `text-on-surface`
- Label / chip: Inter 500, 12px, `text-on-surface-variant`

### 4.4 Spacing rhythm

Page padding: `px-8 py-6`. Card gap in lists: 12px. Section gap: 24px. Sidebar navigation rail: fixed `w-20` left.

### 4.5 Iconography

Google Material Symbols Outlined, only. Common pairs:
- Pass: `check_circle` (filled) in `text-tertiary`
- Fail / critical: `cancel` (filled) in `text-error`
- Advisory / info: `info` (outline) in `text-on-surface-variant`
- Pending / to do: `radio_button_unchecked` (outline)
- Running: 28px circular spinner (border animation)
- Verified / scanned-by: `verified` in `text-on-surface-variant`
- Tool / scanner: `bug_report` (Trivy), `code` (Semgrep)

### 4.6 Tone of voice

| Principle | Example | Anti-pattern |
|-----------|---------|--------------|
| Calm, never alarmist | "3 critical findings need attention" | "DANGER: 3 CRITICAL VULNERABILITIES DETECTED!" |
| Authoritative, not commanding | "The enricher found exploit code available" | "You must patch this immediately" |
| Supportive, not condescending | "Enrich this finding to understand the impact" | "Click here to learn about this vulnerability" |
| Concise, not terse | "No findings match your filters" | "Empty" / "Nothing found" |
| Action-oriented | "Solve" / "Enrich finding" / "Build plan" | "Submit" / "Process" / "Execute" |

### 4.7 Vocabulary (use exactly these terms — never synonyms)

| Term | Means | Never say |
|------|-------|-----------|
| Finding | A vulnerability from a scanner | Vulnerability, issue, alert, CVE |
| Workspace | A remediation session for one finding | Session, ticket, case |
| Posture check | A repo-configuration / hygiene check | Audit, control, rule |
| Agent | A specialized AI sub-agent | Bot, tool, assistant |
| Solve | Start remediation (opens a workspace) | Fix, address, remediate |
| Resolve | Mark workspace as completed | Close, finish, done |
| Severity | Critical / high / medium / low | Priority, risk |
| Posture | The repo's security configuration state | Hygiene, hardening |
| Grade | The letter grade (A–F) | Score, rating |

---

## 5. The product as it exists today (so you know what evolves)

Cliff already ships a working report card from PRD-0002. Below is what you're evolving, not designing from scratch.

### 5.1 Layout map

- **Left side nav (`w-20`)**: Logo · Dashboard · Findings · History · Integrations · (spacer) · Settings (anchored bottom). Fixed. No top bar — this was deleted in PRD-0004.
- **Page content** to the right of the nav, `px-8 py-6`.
- **Workspace pages** add a right-side persistent sidebar (sections: Summary, Evidence, Owner, Plan, Definition of Done, Ticket, Validation).

### 5.2 Existing report card today (PRD-0002 baseline)

Hero section: a circular **grade ring** in `primary-container` showing the letter grade and "X of 5 criteria met". Below the hero: a **completion progress card** (5-slot pill meter), a **vulnerabilities card**, and a flat **posture card** listing 7 checks (pass/fail rows). At the bottom of the page: a **completion ceremony** moment (only when all criteria are met) with a `ShareableSummaryCard` (1200×630 sharable PNG).

### 5.3 What changes for v0.2

- **Posture card** evolves from flat list of 7 to grouped categories (4 groups, 15 checks) — your biggest design surface
- **Completion progress** recalibrates from 5-slot pill meter to a continuous progress bar with 10 tick marks
- **Grade ring** keeps its visual but receives new values (A = 10/10, B = 8–9, C = 6–7, D = 4–5, F = 0–3)
- **Hero section** gains a small "Scanned by: Trivy 0.52 · Semgrep 1.70" metadata line, muted, below subtitle
- **Assessment progress** screen adds a `ToolPillBar` and gains scanner-specific named steps with progress + detail
- **New interstitial**: an "assessment complete" summary screen between progress and report card

---

## 6. The PRD essentials (compressed)

### 6.1 Posture checks — the new full set

15 checks across 4 categories. Some are pass/fail (count toward grade), some are advisory (informational only).

**CI supply chain (new in v0.2)**
1. Actions pinned to SHA — pass/fail, fixable by agent
2. Trusted action sources — pass/fail
3. Workflow trigger scope — **advisory**

**Collaborator hygiene (new in v0.2)**
4. No stale collaborators (>90 days inactive with write access) — pass/fail
5. Broad team permissions — **advisory**
6. Default branch permissions — pass/fail

**Code integrity (mostly new in v0.2)**
7. Secret scanning enabled — pass/fail
8. Code owners file exists — pass/fail, fixable by agent
9. Signed commits — **advisory**
10. Dependabot or Renovate configured — pass/fail, fixable by agent
11. No committed secrets (Trivy secret scan) — pass/fail

**Repo configuration (carried from PRD-0002)**
12. Branch protection enabled — pass/fail
13. SECURITY.md exists — pass/fail, fixable by agent
14. No secrets in code (regex baseline) — pass/fail
15. Lockfile integrity — pass/fail

**Visual treatment of advisory checks:** advisory = `info` icon in `text-on-surface-variant`, no CTA, muted tooltip explaining why it doesn't block. Not a fail. Not a pass. A third state.

### 6.2 The 10-criteria grade

These are the checks that determine the letter grade. Other checks are visible but informational.

1. SECURITY.md present
2. Dependabot/Renovate configured
3. No open critical vulns (Trivy)
4. No open high vulns (Trivy)
5. Branch protection enabled
6. No secrets detected (Trivy secret scan)
7. CI actions pinned to SHAs
8. No stale collaborators
9. Code owners file exists
10. Secret scanning enabled

Grade scale: **A** = 10/10 · **B** = 8–9 · **C** = 6–7 · **D** = 4–5 · **F** = 0–3.

### 6.3 The fixable-by-agent posture checks

Some failing checks have a "Generate" CTA that spawns a workspace where an agent writes the file and opens a draft PR.

| Check | Agent | CTA label |
|-------|-------|-----------|
| Actions not pinned to SHA | sha_pinning generator | "Pin actions to SHA" |
| Code owners file missing | codeowners generator | "Generate code owners" |
| Dependabot missing | dependabot config generator | "Configure Dependabot" |
| SECURITY.md missing | security_md generator | "Generate SECURITY.md" |

These are primary pill buttons (`bg-primary text-on-primary rounded-full px-4 py-2 text-sm font-semibold`). Per PRD-0004 Story 3, on click the row immediately flips into the "Running" state (optimistic) and the button is replaced by a non-interactive chip "Agent is drafting a PR…".

---

## 7. Surface specifications — what to design

### Surface 1 — Report card, posture section (highest priority)

The dashboard hero + posture card, as Alex would see it after their first assessment. Show realistic data: a Grade B repo with 8 of 10 criteria met, 12 pass / 3 fail / 2 advisory across the four posture groups.

**Required elements:**
- Hero: grade ring (B) + "8 of 10 criteria met" + small "Scanned by: Trivy 0.52 · Semgrep 1.70" metadata line
- Vulnerabilities card (count + severity breakdown)
- Posture card title: "Repo posture" + subtitle "12 of 15 checks pass"
- Four category groups in this order: CI supply chain, Collaborator hygiene, Code integrity, Repo configuration
- Each group shows category eyebrow heading + ordered list of `PostureCheckItem` rows
- Mix of states across the rows: To do (with primary CTA), Done (with link to the draft PR on GitHub), and Advisory (info icon, no action). Failed state may also appear — visual only, no action slot in v0.1
- Group progress rail above each category heading: `h-1.5 w-40` indigo bar showing fraction complete (e.g., "Code integrity · 2 of 4 complete")

**Tone reminder:** This is a status page, not a punch list. Calm, scannable, no exclamation marks.

### Surface 2 — Assessment progress (scanner stages)

The view Alex sees after clicking "Run assessment" (or finishing onboarding). The previous report card stays visible beneath the progress, labeled "Previous assessment: B, 3 days ago" — the user should not feel their data vanished.

**Required elements:**
- Header: "Assessing your repository" + circular radar spinner in `primary-container`
- `ToolPillBar`: a horizontal row of tool identity pills — "Trivy 0.52" · "Semgrep 1.70" · "15 posture checks". Each pill shows a tool icon + name. State variants:
  - Pending: `bg-surface-container-high text-on-surface-variant`
  - Active: `bg-primary-container/40 text-primary` with subtle pulse animation
  - Done: `bg-surface-container text-tertiary` with `check_circle` icon
  - Skipped: `bg-surface-container-high text-on-surface-variant/60` line-through with `warning` icon
- A list of dynamic steps. Each step is one of: `pending` (gray dot), `running` (expanded card), `done` (small chip with result summary), or `skipped` (struck-through with reason). Step keys + labels for v0.2:
  - `detect` · "Detecting project type"
  - `trivy_vuln` · "Scanning dependencies with Trivy"
  - `trivy_secret` · "Checking for committed secrets"
  - `semgrep` · "Scanning code with Semgrep"
  - `posture` · "Checking repo posture"
  - `descriptions` · "Writing plain-language descriptions"
- The active step expands into a `rounded-2xl bg-surface-container-lowest p-4` card showing: spinner + label + percentage, a thin progress bar, and a one-line detail string ("Checking 312 dependencies across npm and pip ecosystems…")
- Completed steps collapse to a small chip with a result summary ("12 findings", "0 secrets", "npm + Python detected")

### Surface 3 — Assessment complete summary (new interstitial)

Shown once after the assessment completes, before the report card. Bridges the gap so Alex isn't surprised by 15 checks across 4 categories.

**Required elements:**
- Big success icon: green check in `tertiary-container/40` circle
- Heading "Assessment complete"
- The `ToolPillBar` showing all tools in their final state (done / skipped)
- Three side-by-side cards:
  - **Vulnerabilities** — total count + severity breakdown chips (high/medium/low/code) + which tools found them
  - **Posture** — "X of 15 pass" + names the 4 categories (CI supply chain, Collaborator hygiene, Code integrity, Repo configuration). This is the moment that primes Alex for the grouped posture card on the next screen
  - **Quick wins** — count of items Cliff can fix automatically + 2-3 short labels. This card uses an accent: `bg-primary-container/15`
- Completion preview: "8 of 10 criteria met — grade B" with a mini grade ring
- Single CTA at the bottom: "View your report card →" (primary pill button)
- Tighten: `py-10`, `gap-6`, card `p-4`

**Show-only-when:** First assessment after onboarding, or after a re-assessment when the posture check count changed. Subsequent visits skip this and load the report card directly.

### Surface 4 — Onboarding step 3 (copy + tool pills)

The third step of the 3-step onboarding wizard. The previous two steps (Connect repo, Configure AI) are unchanged.

**Required elements:**
- Step heading: "Start security assessment"
- Updated intro paragraph: "We'll scan your repository using industry-standard security tools (Trivy, Semgrep) and run 15 posture checks on your repo's security configuration. This usually takes 2–5 minutes."
- "Powered by" label + a small pill row showing: "Trivy 0.52" · "Semgrep 1.70" · "15 posture checks" (same `ToolPillBar` component, all in pending state)
- Four step previews (was 3) with time estimates:
  1. Detect your project type — "We scan for lockfiles, config files, and language markers to pick the right tools automatically." (~10 s)
  2. Scan with Trivy — "Industry-standard vulnerability scanner. Checks dependencies, secrets, and misconfigurations across all ecosystems." (~60 s)
  3. Check repo posture — "15 security checks covering CI supply chain, collaborator hygiene, and code integrity." (~30 s)
  4. Write plain-language descriptions — "Our AI translates scan results into clear, actionable summaries." (~60 s)
- Primary CTA: "Start assessment"

### Surface 5 — Completion progress card (10 criteria visual)

Replaces the 5-slot pill meter from PRD-0002. The pill meter at 10 slots looks too cluttered, so we shift to a continuous progress bar with tick marks.

**Required elements:**
- Heading: "Completion progress"
- Subtitle: "8 of 10 criteria met"
- A horizontal progress bar (`h-2`) with 10 tick marks at equal intervals. Filled segment in `bg-primary`, unfilled in `bg-surface-container`. Tick marks subtly lighter, ~50% opacity
- Below the bar: a list of the 10 criteria as small inline chips, met chips in `bg-tertiary-container/30` with `check_circle`, unmet in `bg-surface-container-high` with `radio_button_unchecked`. Two-column layout on desktop, single column on mobile

### Surface 6 — Shareable summary card (text-only refresh)

The 1200×630 social-share PNG generated when Alex reaches Grade A. Mostly unchanged from PRD-0002 — only the criteria count text and a new "Scanned by" line.

**Required elements (delta only):**
- Replace "5 criteria met" → "10 criteria met"
- Add a small line above the Cliff wordmark: "Scanned by: Trivy 0.52 · Semgrep 1.70 · 15 posture checks" in white at 60% opacity, Inter 500, 14px

---

## 8. States to design for each surface

For each interactive component, design the following states:

| State | Visual treatment |
|-------|------------------|
| Default / resting | The state above |
| Hover (interactive elements only) | Subtle background shift or shadow lift — never a 1px border |
| Active / pressed | `active:scale-95` for buttons |
| Disabled | `opacity-50` + `cursor-not-allowed` |
| Loading / running | Spinner + label + optional progress bar |
| Empty (where applicable) | Centered icon + title + subtitle + optional CTA |
| Error | Error icon + error text in `text-error`, background in `bg-error-container/20` |
| Focus-visible | `ring-2 ring-primary/60 ring-offset-2` (keyboard navigation) |
| Reduced motion | All animations disabled or replaced with non-animated equivalents |

---

## 9. Accessibility requirements

Target: **WCAG 2.1 AA**. Specifics:

- **Color is never the only signal.** Severity, status, and state all carry an icon shape AND text label in addition to color
- Keyboard-navigable; visible focus rings on every interactive element
- Touch targets ≥ 44×44 px on mobile
- Status announcements via `role="status" aria-live="polite"`; the completion ceremony uses `aria-live="assertive"` once
- All Material Symbol icons that aren't decorative get `aria-label`; decorative icons get `aria-hidden="true"`
- Text contrast ≥ 4.5:1 for body, ≥ 3:1 for large text and UI components
- Test the four-state posture-row pattern in colorblind simulation (deuteranopia + protanopia) — icon shape + text label must convey state without color

---

## 10. References (attach when prompting Claude design)

These exist in the repo and are useful as inputs but are **not** the authoritative output. Treat them as "what the previous design pass produced; feel free to depart with reason."

| Reference | Path | What it shows |
|-----------|------|---------------|
| Earlier UX spec for PRD-0003 | `docs/design/specs/UX-0003-security-assessment-v2.md` | Detailed component breakdown from the original ux-designer pass |
| Mockup — assessment progress | `frontend/mockups/html/prd-0003-assessment-progress.html` | Tool pills, dynamic steps, summary interstitial in HTML |
| Mockup — report card posture | `frontend/mockups/html/prd-0003-report-card-posture.html` | Grouped posture card layout in HTML |
| Mockup — PRD-0004 alpha blockers | `frontend/mockups/html/prd-0004-v0.1-alpha-blockers.html` | The four-state posture-row pattern + nav consolidation that PRD-0003 inherits |
| The full PRD | `docs/product/prds/PRD-0003-security-assessment-v2.md` | Full user stories and acceptance criteria |
| ADR-0028 — scanner execution | `docs/adr/0028-subprocess-only-scanner-execution.md` | Why Trivy/Semgrep are subprocess-only — affects nothing visible to the user, only the trust story you can lean on in copy |
| ADR-0027 — unified findings | `docs/adr/0027-unified-findings-model.md` | Same — informs the "Vulnerabilities" card content shape |

---

## 11. What success looks like

A maintainer who has never used Cliff can:

1. Open the dashboard and immediately understand their grade, what's failing, and what's fixable in one glance
2. Tell at a glance which posture group needs attention (CI supply chain vs collaborator hygiene vs code integrity vs repo config)
3. Distinguish "this is a hard fail that hurts my grade" from "this is advisory, useful to know"
4. Trust that the scan was thorough — they recognize the tool names (Trivy, Semgrep) and see which ones ran
5. Click one button per fixable check and end up with a draft PR in their repo
6. Reach Grade A and see a celebration moment that doesn't feel cheesy

If a Claude design output enables all six, it's done.

---

## 12. Constraints and watch-outs

- **Don't introduce new color tokens** beyond the Serene Sentinel palette (and the upcoming `warning` token reserved by PRD-0004). If a UI calls for a new color, propose the token and explain why instead of inlining a hex value
- **Don't redesign the side nav, the workspace layout, or the chat surface.** Those are stable
- **Don't redesign the four-state posture-row pattern itself** (To do / Running / Done / Failed with leading icon column + row tint + action slot variants). PRD-0004 owns it. PRD-0003 only contributes new content to fill those rows
- **Don't show severity using raw red/green hexes.** Always use the `error`, `tertiary`, `warning`, or neutral tokens
- **Don't use Title Case or ALL CAPS** outside of the 10px uppercase status label in the posture row's leading column (a PRD-0004 inheritance) and the share-card Cliff wordmark
- **Don't fill the page edge to edge.** The product feels like an editorial gallery, not a dashboard
- **Don't add elements that aren't in the deliverable list above** without flagging why. Scope discipline matters; the design feeds into a single implementation plan

---

## 13. Output format request

For each of the six surfaces above, please produce:

1. A **rendered mockup** (HTML+CSS or SVG, your call — must inline-render)
2. A short **rationale paragraph** explaining the key design choices
3. **State variants** where applicable (default / hover / loading / empty / error / focus-visible)
4. A **handoff note** flagging anything you'd want a developer to know that isn't visible in the mockup itself (e.g., "the progress bar should animate smoothly between values, not jump")

Optional but appreciated: a short list of **alternatives you considered and rejected**, with one-line reasoning. We learn more from your judgment than your finished pixels.

---

_This brief is the canonical hand-off for the v0.2 design pass. Update it as design decisions are made and feed the result back into `docs/design/specs/UX-0003-security-assessment-v2.md` (rev. 2) before the architect refreshes IMPL-0003._
