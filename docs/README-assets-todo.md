# README visual asset checklist

Companion to `README.md`. Replace placeholders in order — each unblocks the next level of visual polish.

## Tier 1 — Ship this week (unblocks first impression)

### Hero screenshot

- **Where:** `docs/assets/screenshots/hero-workspace.png`
- **Dimensions:** 1440×900 @2x (so 2880×1800 exported)
- **Shows:** Workspace page with a real finding open, chat showing one agent run completed, sidebar populated (summary + owner + plan chips)
- **Why:** Currently pointing at `frontend/mockups/screenshots/workspace.png` — fine as a placeholder, but it's the Stitch mockup, not the real app. Replace once the app renders a realistic state end-to-end.
- **Update in README:** swap the `<img src=...>` in the hero `<p align="center">` block

### Logo + wordmark

- **Where:** `docs/assets/brand/cliff-logo.svg` (light) and `cliff-logo-dark.svg` (dark)
- **Dimensions:** 240×64 wordmark, plus icon-only 80×80
- **Why:** Currently using `frontend/public/favicon.svg` (the icon alone) as a stand-in. A wordmark gives Cliff recognizable brand lift.
- **Update in README:** swap the hero `<img src="frontend/public/favicon.svg" ...>` for the wordmark. If you want the GitHub light/dark-mode swap trick Supabase uses, reference both with `#gh-light-mode-only` / `#gh-dark-mode-only` URL fragments.

### Social / Open Graph card

- **Where:** `docs/assets/brand/og-card.png`
- **Dimensions:** 1280×640
- **Shows:** Cliff wordmark, tagline ("Your security team, in chat."), background texture matching the Serene Sentinel palette
- **Why:** Controls what shows up when the repo is shared on Twitter/X, LinkedIn, Slack, Discord. Huge lift for referral traffic.
- **Where it's used:** GitHub repo Settings → Social preview (uploaded via UI, not linked from README)

## Tier 2 — Ship this month (unblocks conversion)

### Hero demo GIF

- **Where:** `docs/assets/screenshots/hero-demo.gif`
- **Length:** 30–60 seconds
- **Captures:** Queue → click Solve → Workspace loads → user types "enrich this finding" → agent card runs → sidebar updates → user types "build a plan" → plan populates → user clicks "draft ticket" → ticket preview appears
- **Why:** Converts 3x better than a static screenshot for OSS READMEs. Cal.com, Supabase, and PostHog all open with one.
- **Tool suggestion:** Use macOS built-in screen recording → convert to GIF with `ffmpeg` or gifski at 12fps, cap at ~5MB so GitHub renders inline.
- **Update in README:** Replace the hero static PNG with a `<img src="docs/assets/screenshots/hero-demo.gif" ...>`, and keep the PNG as a fallback inside a `<picture>` tag for mobile viewers where GIFs auto-play awkwardly.

### Live demo environment

- **Where:** `demo.cliff.dev` (or pick your subdomain)
- **Shows:** A seeded single-user instance with 5–10 demo findings across severity levels
- **Credentials:** Public, posted in README (e.g. `demo / cliff`)
- **Why:** DefectDojo has a live demo in their README — it removes every objection. "Try it in your browser right now" > "clone this and configure that."
- **Update in README:** Replace the "Live hosted demo coming soon at `demo.cliff.dev`" line under `## Demo` with the real URL + credential block.

## Tier 3 — Ship when it's fun (brand polish)

### Earn the Badge preview SVG

- **Where:** `docs/assets/brand/badge-preview.svg`
- **Shows:** A sample Grade-A badge ("Cliff · A · audited 2026-05-12") in the actual style it would render on a user's README
- **Why:** The badge is your growth engine per strategy memory. Showing a visual preview of what users earn makes "Earn the badge" tangible instead of abstract.
- **Update in README:** Insert the SVG inside the `## Earn the badge` section, above the code snippet that shows how to embed it.

### Custom mermaid → polished SVG for agent pipeline

- **Where:** `docs/assets/diagrams/agent-pipeline.svg`
- **Why:** The mermaid block under `## How it works` renders on GitHub but looks generic. A hand-polished SVG with Serene Sentinel colors signals design maturity.
- **Update in README:** Swap the mermaid block for `<img src="docs/assets/diagrams/agent-pipeline.svg" ...>`. Keep the mermaid block as a fallback in a collapsed `<details>` for accessibility.

## Notes

- All assets should be 2x retina — double the stated pixel dimensions when exporting
- Light-mode background: `#f8f9fa`. Dark-mode background: `#0f1417` (suggested; confirm with design system)
- GitHub renders SVG but strips `<script>` — keep SVGs static
- Images over ~1MB slow down README load on mobile — optimize with `tinypng` or `svgo`
