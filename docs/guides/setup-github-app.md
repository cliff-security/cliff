# GitHub App + Device Flow setup

> **Status:** new in v0.1.x (ADR-0035 / IMPL-0010). The legacy fine-grained
> personal access token (PAT) flow continues to work and is **not**
> deprecated. Existing PAT users will see a one-line "switch to the new
> GitHub App" banner once the App is available on their instance.

Cliff connects to GitHub through a **shared GitHub App** that we own,
combined with **GitHub's Device Flow** for per-instance authorization.
That's the same pattern `gh auth login`, the Vercel CLI, and the npm CLI
use. No private key or `client_secret` is shipped to or generated on a
self-hosted instance — only the public `client_id` and the App `slug`.

## What you'll see (end-user)

1. Open **Settings → Integrations**. The GitHub tile shows a **Connect
   GitHub** button.
2. Click it. A new tab opens to
   `https://github.com/apps/<slug>/installations/new` — pick the repo or
   org you want Cliff to access, click **Install**.
3. GitHub redirects you back to Cliff, which immediately shows a
   modal: **"Authorize Cliff on this device"** with a large
   8-character code (e.g. `MNPQ-RSTU`), a copy button, an "Open
   authorization page" link, and a 15-minute countdown.
4. Click **Open authorization page** (it opens
   `https://github.com/login/device` in a new tab). Paste the code,
   click **Authorize**.
5. The modal flips to "Connected as `<your-github-login>`" within a few
   seconds and dismisses itself.

That's it. From this point on, Cliff uses your GitHub App user access
token for every GitHub call. There is **no token to copy and paste, no
PAT to rotate, no scope picker to reason about.**

> _Screenshots: TODO — drop screenshots of the Settings tile, the install
> page, the Cliff modal, and the github.com/login/device authorize
> screen here once the production App is registered._

## Disconnecting

Click **Disconnect** on the GitHub card in Settings → Integrations. This
removes the access token and installation record from your local
Cliff instance.

> **Important:** Disconnecting is local-only by design. We do not have
> the App's `client_secret`, so we cannot ask GitHub to revoke the token
> on your behalf. To revoke it on GitHub's side, visit
> `https://github.com/settings/applications`, find **Cliff** in the
> list, and click **Revoke**.

## Troubleshooting

### "I clicked Install on GitHub and nothing happened in Cliff"

GitHub redirects to the App's `setup_url`, which is **registered
globally per-App on github.com** and currently hard-coded to
`http://localhost:8000/api/integrations/github/setup`. If your Cliff
instance runs anywhere else (Docker remapped to a different host port,
parallel dev stacks, reverse proxy, hosted at a real domain), GitHub's
post-install redirect lands on a URL that doesn't reach your instance.

**The manual recovery flow.** After 30 seconds of polling without a
callback, the device-flow modal automatically shows a **"Couldn't
detect your install"** card with an Installation ID input. To recover:

1. Open the App's installation page on GitHub:
   - Personal installs: `https://github.com/settings/installations`
   - Org installs:
     `https://github.com/organizations/<org>/settings/installations`
2. Click **Configure** next to your Cliff install. Look at the URL —
   it ends with `/installations/<integer>`. Copy that integer.
3. Paste it into the Installation ID input in Cliff and click
   **Connect**.

This goes through the same CSRF state validation as the normal
github.com → Cliff callback would, so a hostile installation_id can't
be bound to your account even if someone tricks you into pasting one.
The state the form submits is bound to the most recent **Connect
GitHub** click in the same tab — if you wait too long or refresh,
restart the connect flow from the catalog tile.

**Alternative**: set `CLIFF_BASE_URL` to your real public URL and run
Cliff on host port 8000 if you control the deployment. A future
release will support a per-instance `setup_url` so self-hosted
operators can avoid the recovery flow entirely.

### "The code expired before I authorized"

Codes are valid for 15 minutes. Click **Try again** in the modal — it
re-issues a fresh code without changing your install on GitHub.

### "I see 'Authorization was canceled'"

This means you clicked Cancel on
`https://github.com/login/device`. Click **Try again** in the modal to
get a fresh code.

### "I get a 503 on Connect"

`CLIFF_GITHUB_APP_CLIENT_ID` is not set. Either configure the env var
on your instance or fall back to the PAT form (which remains fully
supported).

## What permissions does the App ask for?

Cliff needs write access on **Contents** and **Pull requests** so the
remediation_executor agent can push a fix branch and open a draft PR on
your behalf. The other read-only permissions back the posture checks
(branch protection, pinned actions, etc.) and basic repo metadata.

### Required permissions

| Permission | Level | Why |
|---|---|---|
| Contents | **Read & write** | Clone the repo, commit the fix, push the branch |
| Pull requests | **Read & write** | Open the draft PR; comment back on it |
| Metadata | Read-only (mandatory) | Default branch, languages, basic repo info |
| Actions | Read-only | Read workflow files for the `actions_pinned_to_sha` posture check |
| Administration | Read-only | Read branch-protection rules for the `branch_protection` posture check |

> Why these exact levels? See [ADR-0037](../adr/0037-github-app-write-permissions.md).
> Short version: the OAuth user token returned by the device flow
> carries the **intersection** of (App declared permissions) and (user
> repo permissions). If the App declares only `Contents: read` the
> token cannot push **regardless of what the signed-in user can do via
> `gh` CLI or a PAT.** Cliff preflights every executor run with
> `GET /repos/{owner}/{repo}` and refuses to launch the executor when
> `permissions.push` is `false` — fail fast beats a "success" message
> that silently produces an unpushable branch.

### What if I see a "Push to remote failed: Permission denied" error?

That's the symptom of an App whose permissions are still on the V1
read-only set. To fix:

1. Open <https://github.com/settings/apps> (or your org's settings if
   you registered the App there), click **Edit** on your Cliff App.
2. Under **Permissions → Repository permissions** update:
   - **Contents**: Read-only -> **Read & write**
   - **Pull requests**: Read-only -> **Read & write**
   - **Actions**: not set -> **Read-only**
   - **Administration**: not set -> **Read-only**
3. Save. GitHub will tell you "X installations need to approve these
   new permissions" — that's normal.
4. Visit `https://github.com/settings/installations`, click
   **Configure** next to Cliff, and click **Accept new permissions**.
   (Org installs land at
   `https://github.com/organizations/<org>/settings/installations`.)
5. Retry the failed remediation in Cliff — the preflight will
   re-check and the executor will now be able to push.

If after step 5 you still see the error, double-check that the user
who completed the device flow is the same user (or a member of the
same org) who accepted the new permissions in step 4 — the token only
gets re-issued with the new perms after the user (or an org admin)
explicitly approves them.

### How to verify push access

You don't have to wait until you click **Approve** on a remediation to
discover that the App's permissions are wrong. Cliff surfaces the same
preflight result proactively on the Settings page.

1. Open **Settings → Integrations** in the Cliff UI.
2. On the GitHub integration card you'll see one of:
   - **Push verified** (green) — the App can push to the configured
     repo. Nothing to do.
   - **Push blocked** (red) with a one-line reason — the App is
     misconfigured. Follow the inline "How to fix" link (it lands you
     back at the *Required permissions* section above) or run through
     the five-step recovery in the previous section.
   - *Nothing* — no GitHub integration is connected yet. Click
     **Connect** on the GitHub catalog tile first.
3. After fixing the App on github.com, navigate back to Settings — the
   badge re-checks automatically when the result is older than five
   minutes. The cache is keyed on the configured repo URL, so
   disconnecting and reconnecting against a different repo reflects
   immediately rather than echoing the previous repo's verdict.

Under the hood the badge calls
`GET /api/integrations/github/diagnose`, which is a thin wrapper around
the same `check_repo_push_access` helper the executor uses for its
preflight. By construction the badge and the 412 error card you'd see
after clicking **Approve** report the same outcome — so if the badge is
green you can trust that the executor will not fail at git-push time
for a permissions reason.

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

If you're forking Cliff or running a hosted variant, you'll need to
register your own GitHub App. **End users do not need to do any of
this.**

## Register the App on GitHub

1. Go to <https://github.com/settings/apps/new> (or your org's
   equivalent).
2. **GitHub App name:** `Cliff` (or a fork-specific name).
3. **Homepage URL:** your project's homepage.
4. **Setup URL:** `http://localhost:8000/api/integrations/github/setup`
   (V1 — change once we support per-instance overrides).
5. **Redirect on update:** ✓ checked.
6. **Webhook → Active:** ✗ **unchecked.** Webhooks are out of scope for
   V1.
7. **Permissions** (mirror the matrix from
   [the required-permissions section above](#required-permissions);
   ADR-0037 explains why each level is needed):
   - Repository → Contents: **Read & write**
   - Repository → Pull requests: **Read & write**
   - Repository → Metadata: Read-only
   - Repository → Actions: Read-only
   - Repository → Administration: Read-only
   - Repository → Code scanning alerts: Read-only
8. **Where can this GitHub App be installed?** → Any account.
9. Click **Create GitHub App**.
10. On the next page, scroll down to **Device flow** and check
    **Enable Device Flow**.
11. Note the **Client ID** (starts with `Iv23li…`) and the App **slug**
    (the URL slug — usually a lower-case version of the name).

## Plumb the values into Cliff

Set these env vars on the Cliff instance:

```sh
CLIFF_GITHUB_APP_CLIENT_ID=Iv23li...   # public — safe to commit
CLIFF_GITHUB_APP_SLUG=cliff          # public
CLIFF_BASE_URL=http://localhost:8000   # whatever the instance is reachable at
```

Restart Cliff. The Integrations page should now offer **Connect
GitHub** as the primary path. Existing PAT users see the migration
banner.

> Do **not** ship the App's `client_secret` or private key to
> self-hosted users. They're not required for the device flow and we
> reserve them strictly for SaaS-side App authentication
> (JWT-signed installation token issuance) when that lands later.

## User-token expiry

V1 ships with **user-token expiry disabled** on the App side, which
keeps the refresh path off the hot path. The refresh code is in place
(`refresh_user_access_token` in `backend/cliff/integrations/github_app/flow.py`)
and is exercised by tests, so flipping the toggle on the App later is a
configuration change, not a code change.
