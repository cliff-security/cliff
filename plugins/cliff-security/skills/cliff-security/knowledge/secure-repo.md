---
name: "secure-repo"
description: "End-to-end remediation loop on a user's repo: scan → triage → plan → approve → PR → merge → close → re-assess."
version: "0.2.0"
---

# Secure Repo

Engage when the user says "secure this repo", "vibe security", "scan with Cliff", "fix the findings", or asks Claude to drive a remediation flow on a local checkout or remote repo URL.

Prerequisites (do not improvise around them):

- `cliffsec status` must exit 0 with `ready: true`. If not, route to `install.md` (exit 3 + no PID file) or `onboarding.md` (exit 0, `ready: false`) first.
- The repo must be a real GitHub repo. The PR-driven remediation flow needs a remote — purely-local checkouts won't work.

## Hard rules recap (from SKILL.md)

- Never auto-approve a plan. `cliffsec fix` exits 2 when a plan is ready; surface it and wait for explicit "approve" / "yes" / "go".
- Never auto-merge a PR. Show diff via `gh pr view` + `gh pr diff`, then wait for "merge".
- Stop on validation failure (`cliffsec approve` exits 2 with `validation.verdict != "ok"`). Don't call `close`.
- Never invent IDs. Run `cliffsec issues` if you don't have one.

## The remediation loop

### 1. Preflight — one call only

```bash
cliffsec status
```

- Exit 0 + `ready: true` → continue to scan.
- Exit 0 + `ready: false` → `onboarding.md`.
- Exit 3 → `install.md` (if no PID file at `~/.cliff/run/cliff.pid`) or `troubleshooting.md` (if PID file exists).
- Exit 4 → stop, ask user to re-run installer.

Don't re-run `status` between every later step. Once at the top is enough.

### 2. Resolve the repo URL

If the user gave a URL, use it. Otherwise resolve from the local checkout:

```bash
gh repo view --json url -q .url
```

If `gh repo view` fails (no remote, not a git repo, gh not authed), ask the user for the repo URL explicitly instead of guessing.

### 3. Scan

```bash
cliffsec scan <repo_url>
```

- Exit 5 → "no findings — repo is clean", stop here. Mention the current grade if it's in the response, then ask if they want to run a fresh posture-only assessment to confirm.
- Exit 0 → report `finding_count` and `by_severity` to the user in **one line** and continue. Example: `"Scan done — 14 findings (3 critical, 5 high, 6 medium). Triaging."`
- Exit 1 → `troubleshooting.md`.

### 4. Triage

```bash
cliffsec issues --severity critical,high --limit 10
```

If `total > 5`, ask the user which issues to tackle this session (or "all"). Otherwise proceed through them in order. Don't chase low/medium severity unless the user asks.

**Posture findings** surface here too (`type: "posture"`, severity often empty). They map to grade-counting criteria — don't skip them just because they have no CVSS. The fix flow is the same: `cliffsec fix <id>` → review plan → approve → PR → merge → close.

### 5. Fix loop — per issue

```bash
cliffsec fix <issue_id>
```

`fix` **triages first** — it resolves whether the flagged code is actually reachable in the repo — then gates on the verdict (ADR-0051 §6: an issue cannot enter the plan without a `real` verdict). Read the `verdict` field and branch:

- **Exit 0, `cleared: true`** (`verdict: unexploitable` / `false_positive`) — triaged as **noise**: the vulnerable code isn't reachable here. Report the one-line `reason` to the user and move on — there is nothing to fix. (Optionally `cliffsec close <workspace_id>` to dismiss it.) **Do not** invent a fix for a cleared finding.
- **Exit 2, `awaiting: "human_review"`** (`verdict: needs_review`) — reachability couldn't be settled automatically. Surface the `reason` and let the user decide whether it's real; do **not** auto-plan.
- **Exit 2, `awaiting: "plan_approval"`** (`verdict: real`) — the planner ran. The JSON contains `plan.steps`, `plan.interim_mitigation`, and `plan.definition_of_done`. Render that to the user as a **short bullet list** and ask for approval. Wait for an explicit "yes".

This is the core value: noise is cleared with reasoning, only a `real` finding gets a plan. Once a `real` plan is approved:

```bash
cliffsec approve <workspace_id>
```

The CLI runs the executor + validator and waits for the result. Outcomes:

- **Exit 0** — `pr_url` populated, `validation.verdict == "ok"`. Continue to PR review (step 6).
- **Exit 2** — validation didn't pass. Surface `validation.reason` to the user and **stop** for this issue (do not close). Ask if they want to retry or skip.

### 6. PR review

```bash
gh pr view <pr_url> --json title,body,additions,deletions,files
gh pr diff <pr_url>
```

Read the diff. Summarize to the user: what changed, scope (files / lines), risk you can see (e.g. "touches the auth middleware" / "version bump only"). Ask for an explicit "merge" before calling:

```bash
gh pr merge <pr_url> --squash
```

### 7. Close

```bash
cliffsec close <workspace_id>
```

Marks the workspace closed and auto-resolves the linked finding. Exit 0 with `closed: true` → move on to the next issue.

### 8. Re-assess (always run after fixes land)

After the last `cliffsec close` — or whenever the user pauses the loop — re-run the scan to capture the new grade and any newly surfaced posture findings:

```bash
cliffsec scan <repo_url>
```

Then read `/api/assessment/latest`:

```bash
curl -s http://localhost:8000/api/assessment/latest | jq '{grade, criteria: .criteria}'
```

Compare to the pre-fix grade and report:

- Grade went up? Tell the user what flipped.
- Grade unchanged? Surface the still-failing criteria (keys whose value is `false`).
- Grade A reached? Celebrate — and stop.

**Posture criteria that need GitHub repo settings** (not code) — call these out explicitly so the user knows they're action items, not skill bugs:

| Criterion | What unblocks it |
|---|---|
| `branch_protection_enabled` | Enable a branch-protection rule on `main` (Settings → Branches) |
| `secret_scanning_enabled` | Settings → Code security → enable secret scanning |
| `no_stale_collaborators` | Audit Settings → Collaborators; remove dormant accounts |
| `actions_pinned_to_sha` | Pin every `uses:` to a 40-char SHA in `.github/workflows/*` |

Some of those checks return `unknown` (rendered as `null` in the criteria, not `false`) until a GitHub PAT is configured **as an Integration** — the daemon resolves the token from the encrypted vault via the `github` integration row, not from a `GITHUB_TOKEN` env var. If a criterion stays `null` despite the user fixing the GitHub setting, route to `onboarding.md`.

### 9. Report

When the loop ends (no more issues, or user stopped), give the user **one paragraph**: count closed, count deferred, the new grade, links to merged PRs. Don't repeat what they already saw.

## Token discipline

- Always pass `--severity` and `--limit` on `cliffsec issues`.
- Don't ask the CLI for `--verbose` unless something failed.
- Summarize the plan and the PR diff. Don't dump JSON or full diffs into chat.
- Don't run `cliffsec status` between every step.

## What NOT to do

- Don't pre-classify a finding to decide whether to call `fix`. The pipeline handles unknown types; just call `cliffsec fix <id>`.
- Don't chain "fix → approve → merge → close" without each user gate. The gates are the point.
- Don't keep looping after the user says "stop", "pause", "let me look".
- Don't open the GitHub-settings UI yourself. Posture findings that need manual settings are user action items — flag them, don't try to drive them.
