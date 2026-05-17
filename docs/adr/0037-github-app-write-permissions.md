# ADR-0037: GitHub App must declare Contents:write + Pull requests:write

**Date:** 2026-05-17
**Status:** Proposed
**Supersedes:** none
**Relates to:** ADR-0024 (Repo cloning and agentic remediation), ADR-0035 (GitHub App + Device Flow onboarding)

## Context

ADR-0035 chose **user OAuth tokens via the GitHub App's device flow** as the onboarding mechanism, storing the resulting token in the credential vault under `github_personal_access_token` (so the existing MCP-Gateway plumbing works unchanged). ADR-0024 declared that agents perform git operations themselves using `$GH_TOKEN` (clone, branch, push, `gh pr create`).

The Q01R QA campaign (Wave 1.5) found that this combination silently fails on org repos:

> Executor: "Push to remote failed: Permission to cliff-security/NodeGoat.git denied to galanko. The provided GitHub token belongs to user 'galanko' which does not have push access to the cliff-security/NodeGoat repository."

The user (galanko) *does* have push access via gh CLI with a PAT — but the App's OAuth user token does not. The reason is a GitHub fundamental: **a user-to-server token carries the intersection of (App declared permissions) × (user repo permissions).** If the App declares only `contents:read`, the user token cannot push regardless of what the user can do.

The dev test App (`cliff-local-test`) was created with insufficient permissions. The same trap is waiting for any OSS deployment whose maintainer doesn't know to set permissions correctly when creating their own App.

## Decision

The Cliff GitHub App **must** declare these repository permissions:

| Permission | Level | Why |
|---|---|---|
| Contents | **Read & write** | Clone, commit, push branches |
| Pull requests | **Read & write** | Open draft PRs, comment on them |
| Metadata | Read-only (mandatory) | Read repo metadata (default branch, languages, etc.) |
| Actions | Read-only | Read workflow files for the `actions_pinned_to_sha` posture check |
| Administration | Read-only | Read branch protection rules for the `branch_protection` posture check (B23-adjacent) |

No additional account-level or org-level permissions are needed.

We **continue using user OAuth tokens via the device flow** (per ADR-0035). We do *not* switch to installation access tokens at this time. Installation tokens carry the App's full permissions without intersection, which solves a different problem (running without a user signed in), and require shipping or rotating the App's private key — heavier than this wave needs.

## Consequences

### Positive

- A single config change on the App page fixes B30 (push fails on org repos).
- No code rewrite, no new secret handling, no new token-mint path.
- Existing vault + MCP Gateway + agent `$GH_TOKEN` plumbing keeps working unchanged.

### Negative

- The cliff-local-test (dev) and any future prod App must be updated on the GitHub UI. Anyone running their own self-hosted Cliff with their own App must mirror this.
- User OAuth tokens still expire/refresh and depend on the user not revoking the App; that's the same trade-off ADR-0035 made.

### Operational

1. **Update the dev App `cliff-local-test`** (immediate, manual): owner adds Contents:write + Pull requests:write + Actions:read + Administration:read. Existing installation_id holders see an "approve new permissions" banner on next install — that's fine for dev.
2. **Document required permissions in the OSS install guide** so users creating their own App copy the right matrix.
3. **Backend preflight** (covered by IMPL-0014): before triggering the executor, verify the token can push to the target repo. If not, fail loudly with a clear error and a link to "Update your App permissions" docs.

## Alternatives considered

### A. Switch to installation access tokens

GitHub Apps can mint server-to-server installation tokens from the App's private key + installation_id. These carry full App permissions without user intersection.

**Why not:** requires shipping the App's private key as a deployment-time secret (or making each self-hosted user create their own App and manage their own private key). Heavier than required to fix the actual bug. Defer; revisit if we ever need to act without a user present (e.g., scheduled re-assessments).

### B. Keep PAT-only onboarding

Roll back ADR-0035; users continue creating PATs by hand.

**Why not:** ADR-0035's UX win is real — the GitHub App device flow is materially better. The bug is a config issue, not an architecture issue.

### C. Both user tokens and installation tokens (hybrid)

User token for reads, installation token for writes.

**Why not:** complexity for a single-user OSS tool. Hard to justify until we have a use case neither solves alone.

## Amendment — 2026-05-17 (Q01R Wave 2)

Wave 2 QA found that the App declaring `Contents:write` is **not sufficient** for the user-OAuth token from the device flow to actually push. The user-to-server token carries the intersection of (App declared permissions) × (Installation effective permissions for the target) × (user's repo permissions). On an existing installation, declaring new permissions on the App only takes effect after an org admin **re-approves** the install — until then, the installation's effective permissions remain at the pre-amendment subset.

This means two operational realities must be documented in code as well as docs:

1. **Setup URL is per-deployment.** The App's globally-configured Setup URL only fits one canonical deployment (`http://localhost:8000` for dev, the hosted prod URL when shipped). Local/dev/Docker-on-arbitrary-port deployments need a recovery flow to bind the install manually. Implemented by IMPL-0016 (manual `POST /setup/manual` + UI poll-and-recovery).
2. **Runtime push-access verification is mandatory.** Static App-declared permissions don't tell the truth at request time. The `check_repo_push_access` preflight (from IMPL-0014) must consult the installation's effective permissions, not just the user's repo permissions. Implemented by IMPL-0017 (extend `check_repo_push_access`) and surfaced proactively by IMPL-0018 (Settings push-access badge).

The original decision still stands — **user OAuth tokens for git operations** — but the operational story now includes these two enforcement points.

## References

- ADR-0024 — Repo cloning and agentic remediation
- ADR-0035 — GitHub App + Device Flow onboarding
- IMPL-0010 — GitHub App + Device Flow implementation
- IMPL-0014 — Q01R push-token preflight + App permission docs
- IMPL-0016 — Q01R W2: GitHub App callback flexibility (Wave 2 amendment)
- IMPL-0017 — Q01R W2: preflight teeth + terminal-error UI (Wave 2 amendment)
- IMPL-0018 — Q01R W2: push-access diagnostic (Wave 2 amendment)
- GitHub Docs: [Differences between GitHub Apps and OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps)
- GitHub Docs: [About user-to-server requests](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/identifying-and-authorizing-users-for-github-apps)
