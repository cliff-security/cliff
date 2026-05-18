---
name: "Secure Repo"
description: |
  Run Cliff end-to-end on the user's repo from inside Claude Code — install if needed, scan, plan, approve, PR, close. Trigger when the user says "secure this repo", "vibe security", "scan with Cliff", or asks Claude to drive a remediation flow on a local checkout. Also handles troubleshooting when Cliff misbehaves: gathers diagnostics, proposes a fix, and on a real bug drafts a GitHub issue for the user to review. Uses the `cliff` CLI (bundled with the Cliff installer) and `gh` for the PR review/merge + issue-filing steps. Hard rule: never auto-approve plans, auto-merge PRs, or run any troubleshooting write action without explicit user approval — those are user gates.
version: "0.1.3"
category: "security"
tags: [cliff, security, remediation, vibe-security, agent-cli]
---

# Secure Repo

You are driving Cliff on the user's behalf. The user lives in their terminal — your job is to take them from "raw repo" to "fixes merged" with as few prompts as possible while never crossing a real decision boundary unilaterally.

This skill wraps the `cliff` CLI (agent-shaped, JSON output, exit codes encode state) and `gh` (for PR review/merge). Prefer one CLI call over many curl recipes. Trust the exit code — it tells you what to do next.

## Hard rules — never break these

1. **Never auto-approve a plan.** `cliff fix` exits 2 when a plan is ready. Show the plan summary + steps to the user and wait for an explicit "approve" / "yes" / "go" before calling `cliff approve`.
2. **Never auto-merge a PR.** After `cliff approve` returns a `pr_url`, use `gh pr view --json title,body,files,additions,deletions` and `gh pr diff` to summarize the change to the user. Wait for an explicit "merge" before calling `gh pr merge --squash`.
3. **Stop on validation failure.** If `cliff approve` exits 2 with `validation.verdict != "ok"`, do not call `close`. Surface the failure reason and stop.
4. **Never invent IDs.** Only pass IDs the CLI returned. If you don't have one, run `cliff issues` to get one.
5. **Don't silence version mismatch.** If any command exits 4, stop and tell the user to re-run the install one-liner. Do not try to work around it.
6. **Never run a troubleshooting write action without approval.** `stop`, `start`, `restart`, `update`, `config set`, `xattr`, or re-running the installer all require an explicit "yes" before you run them. Read-only diagnostics (`doctor`, `logs`, `--check`, `ps`) are fine to run unprompted.
7. **Never auto-submit a GitHub issue.** Use `gh issue create --web` so it opens the user's browser with the body pre-filled — the user reviews, edits, and clicks Submit. Never call `gh issue create` without `--web` when filing a troubleshooting bug.

## Exit-code contract

Every command emits one JSON object on stdout (or stderr for errors) and exits with:

| Code | Meaning | What you do |
|------|---------|-------------|
| 0 | Success, no human gate needed | Read `next` field, continue |
| 2 | Awaiting human gate (plan / validation) | Surface details, wait for user |
| 3 | Daemon unreachable | Run install path |
| 4 | Version mismatch | Stop, ask user to upgrade |
| 5 | Scan completed with zero findings | Tell user the repo is clean, stop |
| 1 | Generic error | Enter **Troubleshooting** (below). Don't just print the hint — diagnose. |

## Workflow

### 1. Preflight — is Cliff running and configured?

```
cliff status
```

- Exit 0 + `ready: true` → continue to **provider keys** (next).
- Exit 0 + `ready: false` → list `blockers` to the user (e.g. `no_llm_model_configured`) and walk them through the configure step below.
- Exit 3 (daemon down) or "command not found" → install path.
- Exit 4 → ask user to re-run installer.

### 1a. Provider keys — AI model and GitHub PAT

Cliff needs **two** credentials to drive the full loop:

- **AI provider key** (e.g. `OPENAI_API_KEY`) — read by the daemon at boot from env, or stored via `PUT /api/settings/api-keys/{provider}`. The model itself is set via `cliff model set <provider>/<id>` (defaults to `openai/gpt-5-nano`).
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

After both are present, re-run `cliff status` — `ready: true` → continue to scan.

### 2. Install path (only when status fails preflight)

The README is the single source of truth for the install one-liner. Do **not** hardcode a URL.

```bash
curl -fsSL https://raw.githubusercontent.com/cliff-security/cliff/main/README.md \
  | awk '/<!-- install:start -->/{f=1;next}/<!-- install:end -->/{f=0}f'
```

That extracts the canonical install snippet. Show it verbatim to the user, get an explicit "yes" (it's a `curl | sh`), then run it via `Bash`. After it returns, poll `cliff status` until exit 0. If it never comes up, surface the install logs and stop — don't keep retrying.

### 3. Scan

If the user gave a repo URL, use it. Otherwise resolve the local checkout:

```bash
gh repo view --json url -q .url
```

Then:

```
cliff scan <repo_url>
```

- Exit 5 → "no findings — repo is clean", stop here.
- Exit 0 → report `finding_count` and `by_severity` to the user in one line and continue.

### 4. Triage

```
cliff issues --severity critical,high --limit 10
```

If `total > 5`, ask the user which issues to tackle this session (or "all"). Otherwise proceed through them in order. Don't chase low/medium severity unless the user asks.

Posture findings surface here too (`type: "posture"`, severity often empty). They map to grade-counting criteria — don't skip them just because they have no CVSS. The fix flow is the same: `cliff fix <id>` → review plan → approve → PR → merge → close.

### 5. Fix loop — per issue

```
cliff fix <issue_id>
```

Exit 2 means the planner is done and the plan is awaiting approval. The JSON contains `plan.steps`, `plan.interim_mitigation`, and `plan.definition_of_done`. Render that to the user as a short bullet list and ask for approval. **Wait for an explicit yes.**

Once approved:

```
cliff approve <workspace_id>
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
cliff close <workspace_id>
```

This marks the workspace closed and auto-resolves the linked finding. Exit 0 with `closed: true` → move on to the next issue.

### 8. Re-assess (always run after fixes land)

After the last `cliff close` — or whenever the user pauses the loop — re-run the scan to capture the new grade and any newly surfaced posture findings:

```
cliff scan <repo_url>
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

Some of those checks return `unknown` (rendered as `null` in the criteria, not `false`) until a GitHub PAT is configured **as an Integration** — the daemon resolves the token from the encrypted vault via the `github` integration row, not from a `GITHUB_TOKEN` environment variable. If a criterion stays `null` despite the user fixing the GitHub setting, tell them to open the Integrations page in the Cliff UI and connect GitHub with a PAT (scopes: `repo`, `read:org` is enough for the posture probes).

### 9. Report

When the loop ends (no more issues, or user stopped), give the user one paragraph: count closed, count deferred, the new grade, links to merged PRs. Don't repeat what they already saw.

## Token discipline

- Always pass `--severity` and `--limit` on `cliff issues`. Don't list 100 findings when 10 will do.
- Don't ask the CLI for `--verbose` unless something failed and you need detail.
- Don't re-run `cliff status` between every step — once at the start is enough. Run it again only after an unexpected error.
- When showing a plan or PR diff, summarize. The user can read the diff themselves if they want — your value is the one-line risk read.

## Troubleshooting

Engage when:

- A `cliff` command in the main flow exits **1** (generic error).
- A command hangs longer than ~2 minutes with no output.
- The user says "troubleshoot", "it's broken", "something's wrong", "fix the daemon", "cliff isn't working", or anything similar.

Do **not** engage for exit 2 / 3 / 4 / 5 — those have their own paths above.

The flow is fixed: gather → diagnose → propose → verify → escalate. Don't improvise; follow the playbook.

### A. Gather (read-only — no approval needed)

Run all of these once and keep the output for diagnosis + a possible issue draft:

```bash
cliff doctor --json
cliff logs --lines 100 || true
cliff --version
cliff update --check || true   # exit 0 = up to date, exit 2 = newer available
ps -ef | grep -E '(cliff|opencode|uvicorn)' | grep -v grep || true
uname -a
```

These are all safe; the user does not need to approve them. Capture stdout + stderr verbatim — you'll reuse it in Phase E.

### B. Diagnose (match signals against the table)

Cross-reference what you found in Phase A against this table. The mapping is **fixed** — don't invent fixes that aren't here. If nothing matches, go straight to Phase E (escalate).

| Signal | Diagnosis | Proposed action |
|---|---|---|
| `status` exit 3, no PID file at `~/.cliff/run/cliff.pid` | Daemon was never started | `cliff start --detach` |
| `status` exit 3, PID file exists but the recorded process is gone | Crashed orphan, ports possibly leaked | `cliff stop` (sweeps owned children) then `cliff start --detach` |
| `doctor` shows `port.<configured-app-port>` failing | Port conflict | Pick a free port, then `cliff config set CLIFF_APP_PORT=<port>` and `cliff restart` |
| `doctor` shows `port.4096` or `port.4100..4102` failing AND status is daemon-down | OpenCode child leaked from a previous crash | `cliff stop` (the sweep reclaims orphans) then `cliff start --detach` |
| `doctor` shows `opencode` failing with "not found" | OpenCode binary missing or never installed | Re-run the install one-liner |
| `doctor` shows `opencode.quarantine` failing on macOS | Gatekeeper quarantined the binary | `xattr -dr com.apple.quarantine ~/.cliff/bin/opencode` (and `trivy` / `semgrep` if they show the same) |
| `doctor` shows `venv` failing | Backend venv corrupt or removed | Re-run the install one-liner |
| `doctor` shows `credential_key` missing | Encryption key not in env file | Re-run the install one-liner (it generates and persists the key) |
| `doctor` shows `migrations` failing with a SQLite error | DB schema state is bad | **Bug** — escalate (Phase E). Do not propose deleting the DB without explicit user request — it would lose findings + workspaces. |
| `update --check` exit 2 (newer release available) AND symptoms could plausibly be a known fix | Out-of-date install | Offer `cliff update` |
| Logs contain a Python traceback (`Traceback (most recent call last):` or `ERROR  ` lines on every request) | Real bug | Escalate (Phase E) |
| Doctor entirely clean, command still failing | No diagnosis from signals | Escalate (Phase E) |

### C. Propose + gate

For any write action you've identified, format the proposal as one block:

> **Diagnosis:** <one line — what doctor/logs showed>.
> **Proposed fix:** `<the exact command(s)>`.
> **What it changes:** <one line — e.g. "moves Cliff to port 8001 and restarts the daemon">.
> **May I proceed?**

Wait for an explicit "yes" / "go" / "do it". Anything ambiguous → ask again.

The list of writes that require approval (recheck before running):

- `cliff start`, `stop`, `restart`, `update`
- `cliff config set ...`
- `xattr ...` or any other shell command that mutates the system
- Re-running the installer
- **Never** `cliff uninstall` — that removes data and config, and is never an automatic remedy. Only run it if the user explicitly asks to uninstall.

If the user declines, ask if they'd like to file an issue (Phase E) instead.

### D. Verify

After running the approved fix, re-verify before declaring success:

```bash
cliff doctor --json
cliff status   # if the fix involved start/restart
```

- Doctor clean and `status` ready → tell the user "fixed: <one line>" and stop.
- Doctor still failing on the same check → the fix didn't take. Don't loop. Go to Phase E.
- A new check is failing → don't chain another guess. Go to Phase E.

### E. Escalate — file a GitHub issue

Engage when: the table didn't match, the fix didn't work, doctor flagged something the table marks as a bug, or logs show a traceback.

Tell the user:

> "I can't fix this from here — it looks like a real bug in Cliff. Want me to draft a GitHub issue against `cliff-security/cliff` with the diagnostic context I collected? It'll open in your browser pre-filled, so you can review and edit before submitting."

If yes, build a single `gh` command that opens the GitHub compose page in the browser with the body pre-filled. **Always use `--web`.** Never auto-submit.

```bash
gh issue create --repo cliff-security/cliff --web \
  --title "[CLI] <one-line summary>" \
  --body "$(cat <<'EOF'
## What happened
<one-line summary of what the user was trying to do and what went wrong>

## Steps to reproduce
1. <command that failed>
2. <expected vs. actual>

## Environment
- Cliff CLI version: <cliff --version>
- Latest release: <cliff update --check result>
- OS: <uname -a>

## Doctor output
\`\`\`json
<cliff doctor --json output>
\`\`\`

## Recent daemon logs (last 100 lines, secrets redacted)
\`\`\`
<cliff logs --lines 100, with redaction applied>
\`\`\`

## What was already tried
- <each fix that was attempted in Phase C, with its outcome>

---
_Filed via Claude Code (`secure-repo` skill) — please add anything I missed before submitting._
EOF
)"
```

**Redaction — non-negotiable.** Before pasting logs or doctor output into the body, scrub these patterns (replace value with `[REDACTED]`):

- Lines containing `KEY=`, `TOKEN=`, `SECRET=`, `PASSWORD=`, `Authorization:`, `Bearer `, `_TOKEN`, `_KEY`, `api_key`, `apikey`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `CLIFF_CREDENTIAL_KEY` (these are in `~/.cliff/config/cliff.env`)
- Anything that looks like a JWT (`eyJ...`), a GitHub PAT (`ghp_...`, `gho_...`, `github_pat_...`), or a generic 40+ char hex string after `=`

If any line is ambiguous (might or might not be a secret), redact it. Better to over-redact than to leak. Show the user the body **as it will be submitted** before running the `gh` command, and offer to remove anything else they don't want public.

### Token discipline for troubleshooting

- Don't dump the full doctor JSON to the chat — extract the failing checks only.
- Don't paste 100 log lines to the chat — extract the relevant traceback / error window only. The full logs go in the issue body, not the chat.
- Don't run all the Phase A commands again between attempts — once at the top is enough. If you re-run anything, only re-run the specific check you fixed (e.g. just `cliff doctor --json` after a restart).

## When in doubt

- Unknown finding type? Just call `cliff fix <id>` and let the pipeline handle it. Don't pre-classify.
- The CLI returned a `next` field? Use it. The CLI knows what comes next.
- The user said "stop" or "let me look"? Stop. Don't keep the loop running.
