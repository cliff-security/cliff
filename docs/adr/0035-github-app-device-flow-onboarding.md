# ADR-0035: GitHub App + Device Flow onboarding (replace PAT)

**Date:** 2026-05-07
**Status:** Proposed

## Context

Today, OpenSec's only path to "connect a GitHub repo" is a fine-grained
Personal Access Token (PAT) entered in Settings (see
`backend/opensec/integrations/registry/github.json` and
`frontend/src/components/settings/IntegrationSettings.tsx`). The user has
to:

1. Read a multi-step setup guide.
2. Navigate to GitHub developer settings.
3. Pick the right token type (fine-grained vs. classic).
4. Pick the right scopes (Code scanning, Dependabot, Contents, Pull
   requests — and read+write vs. read-only depending on action tier).
5. Pick the right repos.
6. Copy the token.
7. Paste it into OpenSec.

This is a poor first impression for a "secure your repo in one click"
product. It also pushes scope/permission choice onto users who shouldn't
have to think about it — most never grant write access, which silently
disables remediation PRs.

We want the same onboarding shape as `gh auth login`, the Vercel CLI, and
the npm CLI: **"click to install OpenSec on your repo"**, then a short
device-flow confirmation. Two clicks total.

We also want this to keep working in the long-running self-hosted
deployment model — no private key, no `client_secret` ever shipped to or
generated on a self-hosted instance.

## Decision

Adopt a **single shared GitHub App owned by us** (the OpenSec project),
combined with **GitHub's Device Flow** for per-instance user
authorization. The App's `client_id` and `slug` are public values shipped
with the binary (and overridable via env). The App's `client_secret` and
private key are **never** distributed to self-hosted users — they live
only with us, for SaaS use later.

### How it works end-to-end

1. User clicks **Connect GitHub** on the Integrations page.
2. Backend calls `POST https://github.com/login/device/code` with the
   public `client_id`. Receives `device_code`, `user_code`,
   `verification_uri`, `expires_in`, `interval`. The `device_code` stays
   server-side (used for polling). The frontend gets the rest plus a
   public install URL.
3. New tab opens to
   `https://github.com/apps/{slug}/installations/new?state={csrf}`. User
   picks repos and clicks Install.
4. GitHub redirects to the App's configured `setup_url`, which points
   back at the OpenSec instance:
   `http://localhost:8000/api/integrations/github/setup?installation_id=<id>&setup_action=install&state=<csrf>`.
5. OpenSec validates the CSRF state, stores `installation_id`, redirects
   the browser to the Integrations page with a `?github_setup=complete`
   flag.
6. The frontend now shows a modal: **"Authorize OpenSec on this
   device"**. The 8-character `user_code` (`MNPQ-RSTU`) is displayed
   large and copyable. A button auto-opens
   `https://github.com/login/device` in a new tab. A spinner shows live
   polling status and a 15-minute countdown.
7. The user pastes the code on `github.com/login/device` and clicks
   Authorize.
8. Meanwhile, the OpenSec backend has been polling
   `POST https://github.com/login/oauth/access_token` server-side
   (frontend polls our `/status` endpoint, which reads the result the
   poller wrote). On `access_token` returned, OpenSec stores the user
   access token (and refresh token, if expiry is enabled) encrypted in
   the existing credential vault, and marks the integration `connected`.
9. From this point on, OpenSec uses the user access token in
   `Authorization: Bearer <token>` for all repo API calls. The token
   plugs into the existing MCP Gateway credential injection (ADR-0018)
   without changes to the agent code path.

Reference: <https://docs.github.com/en/apps/creating-github-apps/writing-code-with-the-rest-api/using-the-device-flow-to-generate-a-user-access-token-for-a-github-app>

### App configuration (managed by us, off-repo)

- Name: **OpenSec**
- Permissions: `contents:read`, `metadata:read`,
  `security_events:read`, `pull_requests:read` (V1 read-only).
  Higher-tier write permissions for remediation PRs are added in a
  follow-up ADR — they're not in scope for this change.
- Device flow: **enabled**.
- Public install: **yes**.
- Webhook: **disabled** (out of scope for V1).
- User access token expiry: **disabled** for V1 (recommendation —
  simplifies the refresh path; revisit if GitHub forces it).
- `setup_url`: `http://localhost:8000/api/integrations/github/setup`
  (works for the default self-hosted shape; non-default ports/hosts
  fall back to a manual `installation_id` input — see Trade-offs).
- The App's `client_id` and `slug` are exposed via environment:
  `OPENSEC_GITHUB_APP_CLIENT_ID`, `OPENSEC_GITHUB_APP_SLUG`. Both are
  public; safe to ship a default in source.

## Alternatives considered

### A. Keep the PAT flow

**Rejected.** The flow this ADR replaces. High onboarding friction,
forces users to make scope decisions they don't understand, and silently
caps remediation capability when scopes are wrong. Existing PAT users are
left intact (see Migration), but new connections move to the App.

### B. GitHub App Manifest flow (per-user App)

Each self-hosted instance creates its **own** GitHub App via the
manifest flow. UX is "create an app named OpenSec-yourorg", then install
it.

**Rejected** for two reasons:

1. **UX dissonance.** Users want to *install* an app that already
   exists, not *create one*. "What do I name it? Public or private?
   Webhook URL?" — every question is a confusion tax.
2. **No multi-tenant story.** Each instance has a separate App with
   separate identity, so we can't centralize SaaS later, can't ship App
   updates atomically, and lose the trust signal of a single
   verified publisher.

### C. OAuth web flow with `client_secret`

The classic OAuth2 authorization-code-with-secret flow. Cleanest UX
(single redirect, no code-typing).

**Rejected** because it requires shipping the App's `client_secret` in
the self-hosted binary or asking each user to register their own App
again. Either path leaks the secret across thousands of installs — at
which point GitHub revokes it and every install breaks. Hard rule: **no
`client_secret` and no private key on self-hosted, ever.**

### D. Device flow (chosen)

Token exchange requires only the public `client_id`. The private key and
`client_secret` stay with us — used only for SaaS App auth (JWT signing,
installation tokens) when we add hosted later. User access tokens issued
via device flow are scoped to the repos where the App is installed for
that user, with the App's declared permissions — same effective scope
as installation tokens for V1's read-only needs.

## Trade-offs / consequences

### Easier

- **Two-click onboarding** for new users: Install (on github.com) →
  Authorize device (on github.com). No token copy-paste, no scope picker
  on our side.
- **No new crypto subsystem.** Token storage reuses ADR-0016's existing
  AES-256-GCM credential vault; no parallel Fernet key, no second key
  resolution chain.
- **No agent code change.** The user access token replaces the PAT under
  the same credential key (`github_personal_access_token`); the MCP
  Gateway injects it the same way, so workspace agents and the existing
  GitHub MCP server keep working without any awareness of how the token
  was acquired.
- **No `client_secret` or private key on disk.** The self-hosted
  instance only ever sees `client_id` (public) and per-user access
  tokens (already encrypted at rest).
- **Better trust signal.** All installs come from one verified
  publisher's App, not thousands of one-off Apps named
  `opensec-acme-corp-1`.
- **Cleaner SaaS migration later.** When we add hosted, the same App
  identity works for everyone; we just enable JWT/installation-token
  paths server-side without touching self-hosted.

### Harder

- **Two-step UX (install → authorize).** Worse than a single OAuth
  redirect, but standard for CLI-style tools and well-understood.
  Mitigated by aggressive UI affordances (copy button, auto-open
  authorize tab, big visible countdown).
- **`setup_url` quirk on non-default deployments.** Self-hosted users
  who run OpenSec on a non-default host or port (e.g. behind a reverse
  proxy on `:443/opensec/`) won't be redirected back cleanly because
  `setup_url` is configured *on the App* and points at
  `localhost:8000`. **V1 mitigation:** if no `setup` callback fires
  within ~30 seconds after the user clicks Install, the modal shows
  *"Didn't get redirected? Paste your installation URL or
  installation_id here"* with a manual input. Document this in
  `docs/guides/setup-github-app.md`.
- **Token revocation requires `client_secret`.**
  `DELETE /applications/{client_id}/token` requires Basic auth with
  `client_id:client_secret`. We can't revoke from self-hosted. **V1
  trade-off:** `disconnect` deletes the token locally and instructs the
  user to revoke manually at
  `https://github.com/settings/applications`. SaaS will revoke for free
  later. Document clearly.
- **App-level rate limits shared across all self-hosted instances.**
  GitHub rate-limits user access tokens at 5,000 req/hr/user, which is
  per-user, not per-App, so this is fine for V1. (We're not pooling.)
- **Migration carries a slightly larger surface area** — we keep the
  PAT path running in parallel for one alpha cycle. See Migration.

### Migration from PAT

PAT integrations remain a fully-working path. They are not deleted, not
deprecated, and not gated by the new feature flag.

- Existing PAT users see their integration as **"Connected (PAT)"** with
  a one-line banner: *"Switch to the new GitHub App for a better
  experience."*
- One click on the banner triggers the Device Flow modal. On successful
  App connection, the new install becomes the active GitHub integration
  and the old PAT integration row is **disabled (archived)**, not
  deleted. The PAT credential is left in the vault until the user
  explicitly revokes — they may want it back if the App fails for them.
- Behind a runtime feature flag for V1: the new flow is gated on
  `OPENSEC_GITHUB_APP_CLIENT_ID` being set. Unset → only PAT is
  available (today's behavior). Set → both available, App promoted.
  This means the App can ship dark and be flipped on by env without a
  code change.

## Alignment with existing ADRs

- **ADR-0015 (MCP-native integration architecture)** — unchanged. The
  GitHub MCP server is still the runtime; we're swapping the *source of
  the bearer token* the gateway injects into it.
- **ADR-0016 (Credential vault)** — token reuses the existing
  AES-256-GCM vault keyed off the integration row. No parallel
  encryption module, no parallel key resolution. The new GitHub App
  installation table holds non-secret metadata (installation_id, csrf
  state, polling status); secrets stay in the `credential` table.
- **ADR-0017 (Audit logging)** — every state transition in the device
  flow (`connect_initiated`, `device_code_issued`,
  `installation_completed`, `token_received`, `token_refreshed`,
  `disconnect`) emits an audit event. Stays consistent with existing
  schema.
- **ADR-0018 (MCP Gateway)** — unchanged. The gateway still does
  placeholder substitution
  (`${credential:github_personal_access_token}`); the value behind that
  placeholder is now a user access token instead of a PAT. The gateway
  doesn't need to know.
- **ADR-0020 (Two-plane architecture)** — onboarding belongs to the
  operational plane (UI-driven configuration). The agentic plane is
  untouched.

## Out of scope (for this ADR)

- **Webhooks.** Not in V1. Adding them requires a public webhook URL
  per instance, which doesn't exist for localhost-only deployments. A
  follow-up ADR will cover webhook delivery via a relay.
- **GitHub Enterprise Server (GHES).** GHES has its own device-flow
  endpoint paths (`<ghes_host>/login/device/code`) and would need a
  per-instance App. Defer.
- **Write permissions for automated remediation PRs.** The current App
  declares read-only scopes. Lifting to write requires changing the App
  on GitHub's side and a follow-up ADR covering scope-elevation UX (we
  ask the user to install with a higher action tier).
- **Multi-org / org-restricted installs.** GitHub blocks installs into
  orgs that haven't approved the App. We surface that error in V1 but
  don't help the user request approval — that's a docs problem.

## Open questions

1. Should the "complete-auth" flag survive a page reload? (Decision:
   yes — store CSRF + in-flight state server-side keyed off a session
   cookie or local-storage CSRF; reload re-attaches.)
2. Should we support multiple simultaneous GitHub installs (e.g.
   personal account + work org)? (Decision: not in V1. One active
   GitHub integration at a time. Adding more is a UI problem first.)
3. Should we eagerly probe `GET /user` post-connect to validate the
   token and surface the GitHub login? (Decision: yes — store
   `last_validated_at` and the GitHub login on the installation row.
   Costs one API call per connect.)
