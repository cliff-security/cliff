# docs/assets — mirrored directory

> **This directory exists in two repos. Keep them in sync.**

The same `docs/assets/` tree lives in:

| Repo | Path | Visibility |
|------|------|------------|
| `cliff-security/cliff` (this one — public OSS) | `docs/assets/` | public |
| `cliff-security/cliff-os` (private umbrella) | `docs/assets/` | private |

## Why both

The public `cliff` repo needs these assets because `README.md` and a few
other root-level public docs reference them (wordmark, badge SVG, demo
GIFs, screenshots). The private `cliff-os` umbrella keeps the canonical
copy alongside the rest of the brand, GTM, and design material — that's
where new assets are authored and edited.

## Sync rule

**When you change anything in either copy, change it in the other in the
same change.** Don't let the two drift. Concretely:

- **Edit in cliff-os first**, then copy the changed/added files into
  `cliff/docs/assets/`. The cliff-os tree is the canonical one because
  the brand work, identity files, and unprocessed design source live in
  the private repo.
- **If a file is removed**, remove it from both.
- **If a file is renamed**, rename in both — and grep the public `cliff`
  repo for the old name (`README.md`, `CONTRIBUTING.md`, etc.) so links
  don't break.
- **If you add a file**, decide whether the public repo actually needs
  it. If only internal docs use it, keep it private (`cliff-os` only)
  and don't copy.

## What's allowed here

Only assets that are safe to publish. This directory ships to the public
GitHub repo and to anyone who clones it. Do NOT put:

- Internal-only brand drafts (those live in `cliff-os/gtm/brand/`).
- Design specs, mockups, screenshots from non-public features.
- Anything sourced from a private dataset, customer, or partner.

When in doubt, leave it out of `cliff/docs/assets/` and reference it
from `cliff-os/` only.
