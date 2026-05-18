# B37 — preflight false-positive: user-perms fallback returns can_push=true but actual git push fails

**Severity:** P0 for the "real PR via UI alone" end-to-end goal; P1 in isolation
**Wave:** Q01R-W3
**Found:** 2026-05-17, on Approve & generate fix for minimist@1.2.0 (CVE-2021-44906)
**Build:** `cliff:wave3` from `main = 8139bad` (PR #175 merged)

## Context

PR #175 (IMPL-0017) extended `check_repo_push_access` so the executor's preflight consults `GET /repos/{owner}/{repo}/installation` for the App's installation permissions, AND falls back to the existing user-perms verdict if that endpoint is unavailable. That fallback path is exactly what triggered today.

PR #176 (IMPL-0018) added a Settings push-access badge that calls the same helper. The badge rendered **green "Push verified"** before the executor was triggered — also a false positive.

## Reproduce

1. Onboard via Tier-2 (GitHub App user OAuth). User: @galanko (collaborator on cliff-security/NodeGoat with `push=true`).
2. Settings → Integrations → GitHub: **"Push verified"** green badge renders within 1 s.
3. Open a Critical finding → Approve & generate fix.
4. Executor runs 5+ min, makes a local commit, never pushes, reports failure via the new `executor_failed` UX.
5. No PR ever appears on cliff-security/NodeGoat.

## Backend network calls during preflight

```
19:14:35.700  GET https://api.github.com/repos/cliff-security/NodeGoat                  200 OK
19:14:35.908  GET https://api.github.com/repos/cliff-security/NodeGoat/installation     401 Unauthorized
```

- `/repos/{}/{}` with user OAuth token works and returns `permissions.push=true` (user @galanko is a direct collaborator).
- `/repos/{}/{}/installation` requires the App's JWT, not a user OAuth token; returns 401.

PR-C's fallback kicked in:
```python
# pseudo
if not install_perms_available:
    return user_perms_verdict  # can_push=True
```

Executor was cleared to run.

## What the executor actually did

After 5m 11s of bash/edit activity, the executor's structured_output:

```json
{
  "status": "needs_approval",
  "pr_url": null,
  "branch_name": "cliff/fix/minimist-cve-2021-44906",
  "changes_summary": "Updated minimist from 1.2.0 to 1.2.6 in package-lock.json across 4 dependency declarations (main node, coveralls, cypress, and nyc/detect-indent). This patch-level upgrade fixes CVE-2021-44906 (prototype pollution vulnerability in minimist) without introducing breaking changes.",
  "test_results": "skipped",
  "error_details": "Unable to push to remote: GitHub token (galanko user) lacks permissions to push to cliff-security/NodeGoat repository. Commit was created locally (8151b0c) on branch cliff/fix/minimist-cve-2021-44906 but cannot be pushed without valid credentials or repository access permissions. The fix is complete and ready to push with appropriate credentials."
}
```

## Workspace state after executor finished

```bash
$ docker exec cliff-wave3 git -C /data/workspaces/.../repo log --oneline -1
8151b0c fix: minimist: prototype pollution

$ docker exec cliff-wave3 git -C /data/workspaces/.../repo branch -a
* cliff/fix/minimist-cve-2021-44906        ← local only, no upstream
  master
  remotes/origin/HEAD -> origin/master
  remotes/origin/master                    ← no remotes/origin/cliff/...

$ docker exec cliff-wave3 git -C /data/workspaces/.../repo show --stat HEAD
 package-lock.json | 12 ++++++------
 1 file changed, 6 insertions(+), 6 deletions(-)
```

**Two problems in the commit itself, beyond the push issue:**
1. The diff touches `package-lock.json` only — `package.json` still pins minimist to 1.2.0. A reinstall would revert.
2. Tests were skipped (`test_results: "skipped"`).

These are quality-of-fix issues for the executor's planner-prompt; mostly orthogonal to B37 but worth flagging.

## Remote URL embedded in `origin`

```
origin  https://x-access-token:ghu_REDACTED@github.com/cliff-security/NodeGoat
```

`ghu_*` prefix = **User-to-Server** OAuth token from the GitHub App's user-OAuth flow. These tokens carry the intersection of:
- the user's `repo` (or finer) scopes granted to the App at install,
- the App's declared permissions,
- the installation's installation-level permissions,
- the user's actual access to the repo.

The fact that `/repos/{}/{}` returns push=true tells us the *user* can push. It doesn't tell us this *token* can push via git protocol. The check needs ground truth at the wire level.

## Root cause / where it bites

PR-C's IMPL-0017 explicitly anticipated this in its **Risks** block:

> `GET /repos/{owner}/{repo}/installation` endpoint may not be callable with user OAuth tokens. GitHub docs are unclear — some App endpoints require App JWT (signed with the App's private key). If user token returns 403, the fallback to the old check kicks in (no regression) but B35a stays unfixed. Mitigation: verify endpoint accessibility in a quick spike before merging. If user token can't call it, fall back to: mint an installation token using the App private key (deferred — needs IMPL-0019 ADR work) OR add a runtime probe (push a scratch ref, revert).

So this isn't a regression — it's the deferred branch of the IMPL-0017 decision tree, manifesting in practice for the first time.

## Suggested next step (Wave 4 candidates, pick one)

1. **IMPL-0019 — installation tokens.** Mint an installation access token via App JWT for the executor's git push. Cleanest fix; matches GitHub's documented best practice for App-mediated writes. Cost: new ADR + ~80 lines of token-minting + a refresh mechanism (installation tokens expire after 1 hr).
2. **Runtime probe in preflight.** `git push --dry-run` against a scratch ref name. Cheap, immediate, doesn't change the auth model. Cost: ~30 lines + one new test. Trade-off: pulls a small extra round-trip into every preflight; risks a noisy "permission denied" line in server logs that operators may not understand.
3. **OAuth scope check.** Read `X-OAuth-Scopes` from `GET /user` response and reject if `repo` isn't present. Cheap. Doesn't catch SAML-SSO-not-authorized cases or repository-specific revocations. Probably worth adding regardless, as a cheap pre-filter.

Recommended: **(2) runtime probe** as a tactical fix that ships in Wave 4 and unblocks the "real PR" end-to-end story, **and** **(1) installation tokens** as the structural follow-up. (3) is a freebie that catches a few edge cases earlier.

## Knock-on: PR-D (B35c) is also showing a false positive

The Settings page's "Push verified" green badge runs the same `check_repo_push_access` helper. It rendered green for this setup despite the actual push being impossible. Once B37 is fixed, B35c becomes meaningful.

This is worth noting in the IMPL-0019 / runtime-probe write-up — both UI surfaces need to consume the new ground-truth verdict.

## Severity note

In isolation (UI behavior on a real failure), the system works correctly: `executor_failed` triggered, "Needs attention" + Retry rendered, the error_details was surfaced verbatim. PR-C's UI contract is honored.

The severity is high because the entire Wave 2 + Wave 3 effort's stated success criterion — "drive a Critical to a real PR on cliff-security/NodeGoat via UI alone" — is still not met.
