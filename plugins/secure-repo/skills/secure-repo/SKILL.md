---
name: "Secure Repo"
description: |
  Run OpenSec end-to-end on the user's repo from inside Claude Code — install if needed, scan, plan, approve, PR, close. Trigger when the user says "secure this repo", "vibe security", "scan with OpenSec", or asks Claude to drive a remediation flow on a local checkout. Uses the `opensec` CLI (bundled with the OpenSec installer) and `gh` for the PR review/merge step. Hard rule: never auto-approve plans or auto-merge PRs — those are user gates.
version: "0.1.2"
category: "security"
tags: [opensec, security, remediation, vibe-security, agent-cli]
---

# Secure Repo

You are driving OpenSec on the user's behalf. The user lives in their terminal — your job is to take them from "raw repo" to "fixes merged" with as few prompts as possible while never crossing a real decision boundary unilaterally.

This skill wraps the `opensec` CLI (agent-shaped, JSON output, exit codes encode state) and `gh` (for PR review/merge). Prefer one CLI call over many curl recipes. Trust the exit code — it tells you what to do next.

## Hard rules — never break these

1. **Never auto-approve a plan.** `opensec fix` exits 2 when a plan is ready. Show the plan summary + steps to the user and wait for an explicit "approve" / "yes" / "go" before calling `opensec approve`.
2. **Never auto-merge a PR.** After `opensec approve` returns a `pr_url`, use `gh pr view --json title,body,files,additions,deletions` and `gh pr diff` to summarize the change to the user. Wait for an explicit "merge" before calling `gh pr merge --squash`.
3. **Stop on validation failure.** If `opensec approve` exits 2 with `validation.verdict != "ok"`, do not call `close`. Surface the failure reason and stop.
4. **Never invent IDs.** Only pass IDs the CLI returned. If you don't have one, run `opensec issues` to get one.
5. **Don't silence version mismatch.** If any command exits 4, stop and tell the user to re-run the install one-liner. Do not try to work around it.

## Exit-code contract

Every command emits one JSON object on stdout (or stderr for errors) and exits with:

| Code | Meaning | What you do |
|------|---------|-------------|
| 0 | Success, no human gate needed | Read `next` field, continue |
| 2 | Awaiting human gate (plan / validation) | Surface details, wait for user |
| 3 | Daemon unreachable | Run install path |
| 4 | Version mismatch | Stop, ask user to upgrade |
| 5 | Scan completed with zero findings | Tell user the repo is clean, stop |
| 1 | Generic error | Surface the `error.message` and `error.hint` |

## Workflow

### 1. Preflight — is OpenSec running and configured?

```
opensec status
```

- Exit 0 + `ready: true` → continue to **provider keys** (next).
- Exit 0 + `ready: false` → list `blockers` to the user (e.g. `no_llm_model_configured`) and walk them through the configure step below.
- Exit 3 (daemon down) or "command not found" → install path.
- Exit 4 → ask user to re-run installer.

### 1a. Provider keys — AI model and GitHub PAT

OpenSec needs **two** credentials to drive the full loop:

- **AI provider key** (e.g. `OPENAI_API_KEY`) — read by the daemon at boot from env, or stored via `PUT /api/settings/api-keys/{provider}`. The model itself is set via `opensec model set <provider>/<id>` (defaults to `openai/gpt-5-nano`).
- **GitHub PAT** — stored as an **Integration** (the daemon does NOT read `GITHUB_TOKEN` env). Without it, every GitHub-API posture check (`branch_protection_enabled`, `secret_scanning_enabled`, `no_stale_collaborators`, …) returns `unknown` and the grade caps at C.

Verify both:

```bash
# AI provider — env-sourced or db-sourced is fine
curl -s http://localhost:8000/api/settings/api-keys

# GitHub Integration — must have one with adapter_type=github
curl -s http://localhost:8000/api/settings/integrations | jq '.[] | select(.adapter_type=="github")'
```

If the AI key is missing, ask the user for one and store it:

```bash
curl -X PUT http://localhost:8000/api/settings/api-keys/openai \
  -H "Content-Type: application/json" \
  -d '{"provider":"openai","key":"<paste>"}'
```

If the GitHub Integration is missing, **first** confirm with the user, **then** create it and store the PAT:

```bash
# Create the integration
INT_ID=$(curl -s -X POST http://localhost:8000/api/settings/integrations \
  -H "Content-Type: application/json" \
  -d '{"adapter_type":"github","provider_name":"GitHub","enabled":true,
       "config":{"repo_url":"<repo_url>"},"action_tier":1}' | jq -r .id)

# Store the PAT in the encrypted vault
PAT="$(gh auth token)"   # or ask the user for one
curl -X POST "http://localhost:8000/api/settings/integrations/$INT_ID/credentials" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg v "$PAT" '{key_name:"github_personal_access_token", value:$v}')"
```

Required PAT scopes for the posture probes: `repo` (or fine-grained: Contents read, Metadata read, Administration read, Code scanning alerts read, Pull requests read+write for remediation).

After both are present, re-run `opensec status` — `ready: true` → continue to scan.

### 2. Install path (only when status fails preflight)

The README is the single source of truth for the install one-liner. Do **not** hardcode a URL.

```bash
curl -fsSL https://raw.githubusercontent.com/galanko/OpenSec/main/README.md \
  | awk '/<!-- install:start -->/{f=1;next}/<!-- install:end -->/{f=0}f'
```

That extracts the canonical install snippet. Show it verbatim to the user, get an explicit "yes" (it's a `curl | sh`), then run it via `Bash`. After it returns, poll `opensec status` until exit 0. If it never comes up, surface the install logs and stop — don't keep retrying.

### 3. Scan

If the user gave a repo URL, use it. Otherwise resolve the local checkout:

```bash
gh repo view --json url -q .url
```

Then:

```
opensec scan <repo_url>
```

- Exit 5 → "no findings — repo is clean", stop here.
- Exit 0 → report `finding_count` and `by_severity` to the user in one line and continue.

### 4. Triage

```
opensec issues --severity critical,high --limit 10
```

If `total > 5`, ask the user which issues to tackle this session (or "all"). Otherwise proceed through them in order. Don't chase low/medium severity unless the user asks.

Posture findings surface here too (`type: "posture"`, severity often empty). They map to grade-counting criteria — don't skip them just because they have no CVSS. The fix flow is the same: `opensec fix <id>` → review plan → approve → PR → merge → close.

### 5. Fix loop — per issue

```
opensec fix <issue_id>
```

Exit 2 means the planner is done and the plan is awaiting approval. The JSON contains `plan.steps`, `plan.interim_mitigation`, and `plan.definition_of_done`. Render that to the user as a short bullet list and ask for approval. **Wait for an explicit yes.**

Once approved:

```
opensec approve <workspace_id>
```

The CLI runs the executor + validator and waits for the result. Outcomes:

- **Exit 0** — `pr_url` populated, `validation.verdict == "ok"`. Continue to PR review.
- **Exit 2** — validation didn't pass. Surface `validation.reason` to the user and **stop** (do not close).

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

```
opensec close <workspace_id>
```

This marks the workspace closed and auto-resolves the linked finding. Exit 0 with `closed: true` → move on to the next issue.

### 8. Re-assess (always run after fixes land)

After the last `opensec close` — or whenever the user pauses the loop — re-run the scan to capture the new grade and any newly surfaced posture findings:

```
opensec scan <repo_url>
```

Then read `/api/assessment/latest` to get the current grade and `criteria_snapshot`:

```bash
curl -s http://localhost:8000/api/assessment/latest | jq '{grade, criteria: .criteria}'
```

Compare to the pre-fix grade and report:

- Grade went up? Tell the user what flipped.
- Grade unchanged? Surface the still-failing criteria (`criteria_snapshot` keys whose value is `false`).
- Grade A reached? Celebrate — and stop.

Posture criteria that need GitHub repo settings (not code) — call these out explicitly so the user knows they're action items, not skill bugs:

| Criterion | What unblocks it |
|---|---|
| `branch_protection_enabled` | Enable a branch-protection rule on `main` (Settings → Branches) |
| `secret_scanning_enabled` | Settings → Code security → enable secret scanning |
| `no_stale_collaborators` | Audit Settings → Collaborators; remove dormant accounts |
| `actions_pinned_to_sha` | Pin every `uses:` to a 40-char SHA in `.github/workflows/*` |

Some of those checks return `unknown` (rendered as `null` in the criteria, not `false`) until a GitHub PAT is configured **as an Integration** — the daemon resolves the token from the encrypted vault via the `github` integration row, not from a `GITHUB_TOKEN` environment variable. If a criterion stays `null` despite the user fixing the GitHub setting, tell them to open the Integrations page in the OpenSec UI and connect GitHub with a PAT (scopes: `repo`, `read:org` is enough for the posture probes).

### 9. Report

When the loop ends (no more issues, or user stopped), give the user one paragraph: count closed, count deferred, the new grade, links to merged PRs. Don't repeat what they already saw.

## Token discipline

- Always pass `--severity` and `--limit` on `opensec issues`. Don't list 100 findings when 10 will do.
- Don't ask the CLI for `--verbose` unless something failed and you need detail.
- Don't re-run `opensec status` between every step — once at the start is enough. Run it again only after an unexpected error.
- When showing a plan or PR diff, summarize. The user can read the diff themselves if they want — your value is the one-line risk read.

## When in doubt

- Unknown finding type? Just call `opensec fix <id>` and let the pipeline handle it. Don't pre-classify.
- The CLI returned a `next` field? Use it. The CLI knows what comes next.
- The user said "stop" or "let me look"? Stop. Don't keep the loop running.
