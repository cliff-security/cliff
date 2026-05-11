# GitHub App + Device Flow setup

> **Status:** new in v0.1.x (ADR-0035 / IMPL-0010). The legacy fine-grained
> personal access token (PAT) flow continues to work and is **not**
> deprecated. Existing PAT users will see a one-line "switch to the new
> GitHub App" banner once the App is available on their instance.

OpenSec connects to GitHub through a **shared GitHub App** that we own,
combined with **GitHub's Device Flow** for per-instance authorization.
That's the same pattern `gh auth login`, the Vercel CLI, and the npm CLI
use. No private key or `client_secret` is shipped to or generated on a
self-hosted instance — only the public `client_id` and the App `slug`.

## What you'll see (end-user)

1. Open **Settings → Integrations**. The GitHub tile shows a **Connect
   GitHub** button.
2. Click it. A new tab opens to
   `https://github.com/apps/<slug>/installations/new` — pick the repo or
   org you want OpenSec to access, click **Install**.
3. GitHub redirects you back to OpenSec, which immediately shows a
   modal: **"Authorize OpenSec on this device"** with a large
   8-character code (e.g. `MNPQ-RSTU`), a copy button, an "Open
   authorization page" link, and a 15-minute countdown.
4. Click **Open authorization page** (it opens
   `https://github.com/login/device` in a new tab). Paste the code,
   click **Authorize**.
5. The modal flips to "Connected as `<your-github-login>`" within a few
   seconds and dismisses itself.

That's it. From this point on, OpenSec uses your GitHub App user access
token for every GitHub call. There is **no token to copy and paste, no
PAT to rotate, no scope picker to reason about.**

> _Screenshots: TODO — drop screenshots of the Settings tile, the install
> page, the OpenSec modal, and the github.com/login/device authorize
> screen here once the production App is registered._

## Disconnecting

Click **Disconnect** on the GitHub card in Settings → Integrations. This
removes the access token and installation record from your local
OpenSec instance.

> **Important:** Disconnecting is local-only by design. We do not have
> the App's `client_secret`, so we cannot ask GitHub to revoke the token
> on your behalf. To revoke it on GitHub's side, visit
> `https://github.com/settings/applications`, find **OpenSec** in the
> list, and click **Revoke**.

## Troubleshooting

### "I clicked Install on GitHub and nothing happened in OpenSec"

GitHub redirects to the App's `setup_url`, which is hard-coded to
`http://localhost:8000/api/integrations/github/setup` for V1. If your
OpenSec instance runs on a different host or port (e.g. behind a reverse
proxy or on a non-default port), the redirect lands on a URL that
doesn't reach your instance.

**Workarounds:**

1. Set `OPENSEC_BASE_URL` to your real public URL and run OpenSec on
   port 8000 if possible.
2. Or, after Install on GitHub, copy the `installation_id` from the URL
   GitHub redirected you to (it'll look like
   `?installation_id=12345&setup_action=install`) and paste it into the
   manual fallback field that the modal will surface after ~30 seconds.
   The CSRF state in the URL is checked the same way regardless.

A future release will support a per-instance `setup_url` once
self-hosted users start running on non-default hosts more often.

### "The code expired before I authorized"

Codes are valid for 15 minutes. Click **Try again** in the modal — it
re-issues a fresh code without changing your install on GitHub.

### "I see 'Authorization was canceled'"

This means you clicked Cancel on
`https://github.com/login/device`. Click **Try again** in the modal to
get a fresh code.

### "I get a 503 on Connect"

`OPENSEC_GITHUB_APP_CLIENT_ID` is not set. Either configure the env var
on your instance or fall back to the PAT form (which remains fully
supported).

## What permissions does the App ask for?

V1 is read-only:

- **Contents: Read** — read code for context (CODEOWNERS, vulnerable
  files, configs).
- **Metadata: Read** — basic repo metadata.
- **Code scanning alerts: Read** — pull CodeQL findings.
- **Pull requests: Read** — link existing PRs to remediations.

A future scope-elevation flow will let you grant `Contents: Write` and
`Pull requests: Write` so OpenSec can create remediation PRs
automatically. Until then, OpenSec drafts the patch and asks you to
push it.

## What's stored, where?

| Data | Where | Encryption |
|------|-------|------------|
| User access token | `credential` table, key `github_personal_access_token` | AES-256-GCM (ADR-0016) — same as the PAT flow |
| Refresh token (if any) | `credential` table, key `github_refresh_token` | AES-256-GCM |
| Installation metadata | `github_app_installation` table | Plaintext (no secrets) |
| In-flight device code | `credential` table, key `github_device_code`; deleted on terminal state | AES-256-GCM |

The MCP Gateway (ADR-0018) substitutes
`${credential:github_personal_access_token}` into the GitHub MCP server
config the same way it does for PAT-based installs. Workspaces and
agents don't know whether the bearer is a PAT or a user access token.

---

# For administrators / forks

If you're forking OpenSec or running a hosted variant, you'll need to
register your own GitHub App. **End users do not need to do any of
this.**

## Register the App on GitHub

1. Go to <https://github.com/settings/apps/new> (or your org's
   equivalent).
2. **GitHub App name:** `OpenSec` (or a fork-specific name).
3. **Homepage URL:** your project's homepage.
4. **Setup URL:** `http://localhost:8000/api/integrations/github/setup`
   (V1 — change once we support per-instance overrides).
5. **Redirect on update:** ✓ checked.
6. **Webhook → Active:** ✗ **unchecked.** Webhooks are out of scope for
   V1.
7. **Permissions** (read-only for V1):
   - Repository → Contents: Read-only
   - Repository → Metadata: Read-only
   - Repository → Code scanning alerts: Read-only
   - Repository → Pull requests: Read-only
8. **Where can this GitHub App be installed?** → Any account.
9. Click **Create GitHub App**.
10. On the next page, scroll down to **Device flow** and check
    **Enable Device Flow**.
11. Note the **Client ID** (starts with `Iv23li…`) and the App **slug**
    (the URL slug — usually a lower-case version of the name).

## Plumb the values into OpenSec

Set these env vars on the OpenSec instance:

```sh
OPENSEC_GITHUB_APP_CLIENT_ID=Iv23li...   # public — safe to commit
OPENSEC_GITHUB_APP_SLUG=opensec          # public
OPENSEC_BASE_URL=http://localhost:8000   # whatever the instance is reachable at
```

Restart OpenSec. The Integrations page should now offer **Connect
GitHub** as the primary path. Existing PAT users see the migration
banner.

> Do **not** ship the App's `client_secret` or private key to
> self-hosted users. They're not required for the device flow and we
> reserve them strictly for SaaS-side App authentication
> (JWT-signed installation token issuance) when that lands later.

## User-token expiry

V1 ships with **user-token expiry disabled** on the App side, which
keeps the refresh path off the hot path. The refresh code is in place
(`refresh_user_access_token` in `backend/opensec/integrations/github_app/flow.py`)
and is exercised by tests, so flipping the toggle on the App later is a
configuration change, not a code change.
