# Q01R-B30 — Executor push fails: GitHub App OAuth user token has no push scope on org repo

**Severity**: P0
**Surface**: backend (GitHub integration) + GitHub App configuration

## What I observed
After driving the minimist Critical finding through plan + approve + executor (the last two via curl per B29), the executor completed but produced no PR.

`/agent-runs` shows the executor's structured output:
```
{
  "status": "needs_approval",
  "pr_url": null,
  "branch_name": "opensec/fix/minimist-cve-2021-44906",
  "changes_summary": "Updated minimist from 1.2.0 to 1.2.6 in package-lock.json...",
  "error_details": "Push to remote failed: Permission to cliff-security/NodeGoat.git denied to galanko. The provided GitHub token belongs to user 'galanko' which does not have push access to the cliff-security/NodeGoat repository. A token with appropriate permissions or a repository maintainer is required to complete the PR creation."
}
```

But `galanko` IS a maintainer of cliff-security/NodeGoat — the same user has merged 20+ PRs there earlier this week with the same gh CLI token.

## Root cause hypothesis
The Cliff onboarding ran a **GitHub App OAuth device flow** ("opensec-local-test" app, installation_id=133122855). That flow produces a **user access token whose permissions are intersected with the App's declared permissions** — not the user's full scope.

If `opensec-local-test` declares `Contents: read` (or no Contents at all), then the user token returned by the device flow cannot push, regardless of the user's actual repo perms.

Confirmed by the executor's error wording: "*the provided GitHub token belongs to user 'galanko' which does not have push access*" — that's a token-scope check failing, not a user-membership check failing.

## Impact
**This and B29 together fully block the UI-only happy path.** Any user who onboards via the recommended "Install the cliff GitHub App" route, picks a real repo, and lets agents run will get:
- An executor "Success" message at the activity log
- Local file changes that nobody can ever push
- No PR
- A finding that stays at `status=in_progress` forever

This is the central QA-0001 promise broken. PAT path probably works but is not the recommended one.

## Suggested fix
Two-sided:
1. **GitHub App config**: ensure `opensec-local-test` (and the prod app, if separate) requests `Contents: write` and `Pull requests: write` permissions on installation. Verify in the installation acceptance UI.
2. **Backend**: when pushing/creating PRs, prefer the *installation token* (created on demand from the app's private key + installation_id) over the user OAuth token. Installation tokens carry the App's full declared write permissions; user OAuth tokens carry the intersection of App perms × user perms.
3. **UI surface**: when the executor finishes with `error_details` like this, surface it loudly. Right now `next_action_hint` mentions "A repository maintainer or a token with appropriate permissions must push this branch" — but the UI side panel still says "Thinking…" (see B28).

## Workaround for this session
None possible via UI. Would need to:
- Switch to PAT path (B-side onboarding option) with a full-scope user PAT, OR
- Push the branch manually via local gh CLI

## Evidence
- `evidence/Q01R/B30-executor-output.json` (full run record)
- Workspace `e611dc21-0899-4252-b38f-92e23d20c316`, finding `a84e31fb-a26d-4c0f-9e65-f80ad8eb3834`
